import asyncio
from discord import Attachment, app_commands, Interaction
from discord.app_commands import AppCommandError
from discord.ext import commands, tasks
from escpos.exceptions import DeviceNotFoundError  # pyright: ignore[reportMissingTypeStubs]
from escpos.printer import Network  # pyright: ignore[reportMissingTypeStubs]
import logging
import platform
import subprocess
from zoneinfo import ZoneInfo

from characters import UnicodeCharacterPrinting
from image import print_image

logger = logging.getLogger(__name__)

# ESC/POS command to cut the paper fully after 16 feed
feed_cut = bytes([
    0x1D, 0x56,
    65,  # m=65 (full cut)
    16  # n=16 (lines to feed)
])


class Print(commands.Cog):
    """
    Discord.py cog for printing receipts.
    """
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.receipt_ongoing: bool = False

        self.printer_ip = '192.168.0.3'
        self.printer = Network(self.printer_ip, timeout=1, profile='TM-T88V')
        self.unicode_char_print = UnicodeCharacterPrinting(self.printer)

        self.tz = ZoneInfo('Europe/Amsterdam')

        self.task_ping_printer.start()

    @tasks.loop(seconds=30)
    async def task_ping_printer(self) -> None:
        """
        Printer ping task, clears character cache when down.
        """
        count_param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', count_param, '1', '-w', '1', self.printer_ip]

        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        await proc.communicate()

        if proc.returncode != 0:
            # Clear unicode character cache
            self.unicode_char_print.clear()
            logging.info('Printer is down')
        else:
            logging.info('Printer is up')

    @app_commands.command()
    @app_commands.checks.cooldown(1, 10)
    async def print(
        self,
        interaction: Interaction,
        message: str | None,
        image: Attachment | None,
        qr_content: str | None
    ) -> None:
        """
        Print a receipt.

        Parameters
        ----------
        message
            Text message
        image
            Image (1MB limit)
        qr_content
            QR code content
        """
        logging.info(f'Printing command issued by {interaction.user.name}')

        if message is None and image is None and qr_content is None:
            await interaction.response.send_message(
                'This command requires at least one input.',
                ephemeral=True
            )
            return

        # Check image validity
        if image and not (image.content_type
                and image.content_type.startswith('image')
                and image.size <= 10240000):
            await interaction.response.send_message(
                'Please attach a usable image (1MB limit).',
                ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True)

        created_at = interaction.created_at.astimezone(self.tz)

        self.printer.open()

        self.printer.set_with_default(bold=True, underline=True)
        self.unicode_char_print.text(interaction.user.name)
        self.printer.set(bold=False)
        self.unicode_char_print.text(f' {created_at:%Y-%m-%d %H:%M}\n')
        self.printer.set(
            underline=False,
            double_width=True, double_height=True
        )

        if message:
            self.unicode_char_print.text(f'{message.strip()}\n')
        if image:
            print_image(self.printer, await image.read())
        if qr_content:
            self.printer.qr(qr_content, size=8, center=True)  # pyright: ignore[reportUnknownMemberType]

        self.printer.close()

        self.receipt_ongoing = True

        await interaction.followup.send('Your message has been printed.')

    @app_commands.command()
    @app_commands.checks.cooldown(1, 10)
    async def cut(self, interaction: Interaction) -> None:
        """
        Cut the receipt.
        """
        logging.info(f'Cut command issued by {interaction.user.name}')

        if self.receipt_ongoing:
            await interaction.response.defer(thinking=True)

            self.printer.open()
            self.printer._raw(feed_cut)  # pyright: ignore[reportPrivateUsage]
            self.printer.close()

            self.receipt_ongoing = False

            await interaction.followup.send('The receipt has been cut.')
        else:
            await interaction.response.send_message('No receipt to cut.')

    @print.error
    @cut.error
    async def error(
        self,
        interaction: Interaction,
        error: AppCommandError
    ) -> None:
        """
        Method that handles erroneous interactions.
        """
        if isinstance(error, app_commands.errors.CommandOnCooldown):
            await interaction.response.send_message(
                'This command is on cooldown for '
                f'{error.retry_after:.0f} more seconds.',
                ephemeral=True
            )
            return

        if (isinstance(error, app_commands.errors.CommandInvokeError)
                and isinstance(error.original, DeviceNotFoundError)):
            await interaction.followup.send(
                'The printer is currently offline.'
            )
            # Clear unicode character cache
            self.unicode_char_print.clear()
            return

        logger.error(error)
        await interaction.followup.send(
            'Something went wrong, please try again later.'
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Print(bot))
