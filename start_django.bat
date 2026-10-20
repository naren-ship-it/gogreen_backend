@echo off
cd "D:\Tamil Vanan\go green be"
call venv\Scripts\activate
daphne -b 0.0.0.0 -p 8005 electricity_monitoring_be.asgi:application