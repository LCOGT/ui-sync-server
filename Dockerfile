# Dockerfile
FROM python:3.8.10
WORKDIR /application
RUN pip install flask flask-cors flask-socketio gunicorn==20.1.0 eventlet==0.30.2
COPY . /application
EXPOSE 8000
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "-b", "0.0.0.0", "application:app"]