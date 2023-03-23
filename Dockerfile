FROM --platform=linux/amd64 python:3.9-bullseye

RUN mkdir -p /app/etherscan-cache
WORKDIR /app/etherscan-cache

ADD requirements.txt  ./
RUN pip3 install -r requirements.txt

ADD . /app/etherscan-cache

ENTRYPOINT ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
