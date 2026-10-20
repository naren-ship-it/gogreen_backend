import subprocess
import os

def get_pid(port):
    result = subprocess.run(
        f'netstat -ano | findstr :{port}',
        shell=True, capture_output=True, text=True
    )
    lines = result.stdout.strip().split('\n')
    for line in lines:
        if 'LISTENING' in line:
            pid = line.strip().split()[-1]
            return pid
    return None

def stop_server(port=8005):
    pid = get_pid(port)
    if pid:
        os.system(f'taskkill /PID {pid} /F')
        print(f"✅ Server stopped (PID: {pid})")
    else:
        print("❌ No server running on port 8005")

stop_server(8005)