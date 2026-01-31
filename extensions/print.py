import asyncio
from collections.abc import Callable
from discord import Attachment, app_commands, Interaction
from discord.app_commands import AppCommandError
from discord.ext import commands, tasks
from escpos.exceptions import DeviceNotFoundError  # pyright: ignore[reportMissingTypeStubs]
from escpos.printer import Network  # pyright: ignore[reportMissingTypeStubs]
import logging
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

        # Printing queue
        self.queue: asyncio.Queue[Callable[[], None]] = asyncio.Queue(10)
        self.printer_online_event: asyncio.Event = asyncio.Event()

        self.receipt_ongoing: bool = False

        self.printer_ip = '192.168.0.3'
        self.printer = Network(self.printer_ip, timeout=1, profile='TM-T88V')
        self.unicode_char_print = UnicodeCharacterPrinting(self.printer)

        self.tz = ZoneInfo('Europe/Amsterdam')

        self.print_queue_worker.start()
        self.task_printer_status.start()

    async def check_printer_status(self) -> None:
        """
        Printer status check, clears character cache when down.
        """
        def is_online() -> bool:
            """
            Check if the printer is online.
            """
            self.printer.open()
            printer_online = self.printer.is_online()
            self.printer.close()
            return printer_online

        try:
            printer_online = await asyncio.to_thread(is_online)
        except:
            printer_online = False

        if printer_online != self.printer_online_event.is_set():
            if printer_online:
                logger.info('Printer is up')
                self.printer_online_event.set()
            else:
                logger.info('Printer is down')
                self.printer_online_event.clear()
                # Clear unicode character cache
                self.unicode_char_print.clear()

    @tasks.loop(seconds=1)
    async def print_queue_worker(self) -> None:
        """
        Print queue worker to perform blocking jobs in a thread.
        """
        while True:
            job = await self.queue.get()
            # Check if the printer is online
            await self.check_printer_status()
            # Wait if the printer is offline
            await self.printer_online_event.wait()
            # Perform print job
            await asyncio.to_thread(job)
            self.queue.task_done()

    @tasks.loop(seconds=30)
    async def task_printer_status(self) -> None:
        """
        Printer status task.
        """
        await self.check_printer_status()

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
        def print_job() -> None:
            """
            Print job.
            """
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
                print_image(self.printer, image_bytes)
            if qr_content:
                self.printer.qr(qr_content, size=8, center=True)  # pyright: ignore[reportUnknownMemberType]

            self.printer.close()

        logger.info(f'Printing command issued by {interaction.user.name}')

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

        # Get the image data
        if image:
            image_bytes = await image.read()

        # Put the job in the queue
        try:
            self.queue.put_nowait(print_job)
        except asyncio.QueueFull:
            await interaction.followup.send(
                'Print queue is full, please try again later.'
            )
            return

        self.receipt_ongoing = True

        if self.printer_online_event.is_set():
            await interaction.followup.send('Your message has been printed.')
        else:
            await interaction.followup.send(
                'Your message has been queued, '
                'waiting for the printer to come back online.'
            )

    @app_commands.command()
    @app_commands.checks.cooldown(1, 10)
    async def cut(self, interaction: Interaction) -> None:
        """
        Cut the receipt.
        """
        def cut_job() -> None:
            """
            Cut job.
            """
            self.printer.open()
            self.printer._raw(feed_cut)  # pyright: ignore[reportPrivateUsage]
            self.printer.close()

        logger.info(f'Cut command issued by {interaction.user.name}')

        if self.receipt_ongoing:
            await interaction.response.defer(thinking=True)

            # Put the job in the queue
            try:
                self.queue.put_nowait(cut_job)
            except asyncio.QueueFull:
                await interaction.followup.send(
                    'Print queue is full, please try again later.'
                )
                return

            self.receipt_ongoing = False

            if self.printer_online_event.is_set():
                await interaction.followup.send('The receipt has been cut.')
            else:
                await interaction.followup.send(
                    'Receipt cutting queued, '
                    'waiting for the printer to come back online.'
                )
        else:
            await interaction.response.send_message('No receipt to cut.')

    @print_queue_worker.error
    async def task_error(self, error: BaseException) -> None:
        """
        Method that handles erroneous tasks.
        """
        if isinstance(error, DeviceNotFoundError):
            if self.printer_online_event.is_set():
                logger.info('Printer is down')
                self.printer_online_event.clear()
                # Clear unicode character cache
                self.unicode_char_print.clear()
            return
        logger.error(error)

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

        logger.error(error)
        if interaction.response.is_done():
            await interaction.followup.send(
                'Something went wrong, please try again later.'
            )
        else:
            await interaction.response.send_message(
                'Something went wrong, please try again later.'
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Print(bot))
