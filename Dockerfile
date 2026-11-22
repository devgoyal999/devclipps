FROM python:3.10-slim
RUN apt-get update && apt-get install -y libegl1 libdbus-1-3 libfontconfig1 libfreetype6 libxkbcommon0 libpulse0
WORKDIR /app
COPY ./app
RUN pip install-r requirements.txt'
CMD "["xvfb-run","python","main.py"]
