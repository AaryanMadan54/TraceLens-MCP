FROM python:3.11-slim
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN pip install --no-cache-dir --no-deps . && useradd --create-home tracelens && mkdir /runs && chown tracelens /runs
USER tracelens
ENTRYPOINT ["tracelens"]
CMD ["investigate", "--mode", "fixture", "--scenario", "transient", "--run-dir", "/runs/demo"]
