FROM python:3.13-slim

WORKDIR /app

ENV VIRTUAL_ENV=/opt/python_modules
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN apt-get update && apt-get install -y gcc

COPY RakuSpace.py /app
COPY setup_db.py /app
COPY requirements.txt /app
COPY templates/ /app/templates
COPY rakuspace.cfg.example /app/rakuspace.cfg

RUN pip install --no-cache-dir -r /app/requirements.txt
RUN python setup_db.py 

ENTRYPOINT ["granian"]
CMD ["--host", "0.0.0.0", "--port", "6868", "--interface", "wsgi", "RakuSpace:app"]
