FROM python:3.14.2 AS unifont_build

# Fetch unifont hex
COPY get_unifont.sh .
RUN chmod +x get_unifont.sh
RUN ./get_unifont.sh

# Create unifont pickle
COPY characters/unifont.py .
RUN python unifont.py

FROM python:3.14.2-alpine

ENV PYTHONUNBUFFERED=1

RUN addgroup -S app && adduser -s /bin/false -SDH -G app app

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    rm requirements.txt

# Copy Python files
COPY characters/*.py characters/
COPY extensions/*.py extensions/
COPY image/*.py image/
COPY main.py .
# Copy Unifont pickle
COPY --from=unifont_build unifont-*.pickle .

USER app

CMD [ "python", "./main.py" ]
