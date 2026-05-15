#!/bin/bash
# restart_servers.sh - Script to restart servers on EC2

echo "Stopping existing servers..."
pkill -f "run_admin_web.py"
pkill -f "run_user_web.py"
sleep 2

echo "Killing any processes on ports 7860 and 7861..."
sudo lsof -ti:7860 | xargs -r kill -9
sudo lsof -ti:7861 | xargs -r kill -9
sleep 1

echo "Setting environment variables..."
export LLM_PROVIDER=gemini
export GEMINI_API_KEY="AIzaSyBcZhG3moHkC5RN_Ke0kAbfFkq5C0jmXM8"

cd ~/knowledge-system

echo "Starting admin server..."
nohup poetry run python run_admin_web.py > admin.log 2>&1 &
ADMIN_PID=$!

sleep 2

echo "Starting user server..."
nohup poetry run python run_user_web.py > user.log 2>&1 &
USER_PID=$!

sleep 5

echo ""
echo "=========================================="
echo "Servers started!"
echo "Admin PID: $ADMIN_PID"
echo "User PID: $USER_PID"
echo "=========================================="
echo ""
echo "Admin interface: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):7860"
echo "User interface: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):7861"
echo ""
echo "Check logs:"
echo "  tail -f admin.log"
echo "  tail -f user.log"
echo ""
