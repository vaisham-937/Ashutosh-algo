# Utho Cloud Deployment Guide - AshAlgo Trading Platform

Complete step-by-step guide to deploy your trading application on Utho Cloud with HTTPS, encryption, and automated daily resets.

---

## 📋 Prerequisites

### What You Need

- ✅ Utho Cloud VPS (Ubuntu 20.04/22.04)
- ✅ Server IP: `134.195.138.91`
- ✅ Domain name (e.g., `trading.yourdomain.com`) pointed to server IP
- ✅ SSH access (root or sudo user)
- ✅ Local development completed and tested

### Domain DNS Setup

Before starting, configure your domain DNS:

```
Type: A Record
Host: trading (or @)
Points to: 134.195.138.91
TTL: 3600
```

Wait 10-30 minutes for DNS propagation. Verify:
```bash
nslookup trading.yourdomain.com
# Should return: 134.195.138.91
```

---

## 🚀 Deployment Steps

### Step 1: Initial Server Setup

#### 1.1 Connect to Server

```bash
ssh root@134.195.138.91
```

#### 1.2 Update System

```bash
sudo apt update
sudo apt upgrade -y
```

#### 1.3 Install Required System Packages

```bash
# Python 3 and pip
sudo apt install -y python3 python3-pip python3-venv

# Redis server
sudo apt install -y redis-server

# Git (optional, for version control)
sudo apt install -y git

# Build tools (for Python packages)
sudo apt install -y build-essential python3-dev

# Certbot and nginx (for SSL)
sudo apt install -y certbot nginx python3-certbot-nginx
```

#### 1.4 Configure Redis

```bash
# Start and enable Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test Redis connection
redis-cli ping
# Should return: PONG
```

#### 1.5 Configure Firewall

```bash
# Allow SSH, HTTP, HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw --force enable

# Check status
sudo ufw status
```

---

### Step 2: Upload Application Code

#### 2.1 Create Application Directory

```bash
sudo mkdir -p /var/www
cd /var/www
```

#### 2.2 Upload Code from Local Machine

**From your Windows machine** (open PowerShell in project directory):

```powershell
# Upload entire project
scp -r C:\Users\Acer\OneDrive\Desktop\Ashutosh_Chartink_Cilent-2 root@134.195.138.91:/var/www/

# Or upload specific files (if already exists)
scp app/main.py root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/app/
scp app/crypto.py root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/app/
scp app/redis_store.py root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/app/
scp requirements.txt root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/
scp setup_letsencrypt.sh root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/
```

**Alternative: Using Git** (if you have a repository):

```bash
cd /var/www
git clone https://github.com/yourusername/Ashutosh_Chartink_Cilent-2.git
cd Ashutosh_Chartink_Cilent-2
```

---

### Step 3: Setup Python Environment

#### 3.1 Create Virtual Environment

```bash
cd /var/www/Ashutosh_Chartink_Cilent-2

# Create virtual environment
python3 -m venv myvenv

# Activate virtual environment
source myvenv/bin/activate
```

#### 3.2 Install Python Dependencies

```bash
# Upgrade pip
pip install --upgrade pip

# Install requirements
pip install -r requirements.txt

# Verify installation
pip list
# Should show: fastapi, uvicorn, redis, kiteconnect, cryptography, python-dotenv, etc.
```

---

### Step 4: Initialize Encryption

#### 4.1 Run Encryption Setup

```bash
# Still in virtual environment
python init_encryption.py
```

**Expected output**:
```
============================================================
  AshAlgo Trading - Encryption Initialization
============================================================

✅ Created/Updated .env file with encryption key
   Encryption Key: gAAAAABh5K2x...

✅ .env already in .gitignore

🔬 Testing encryption...
🔐 Encryption enabled - API credentials will be encrypted
✅ Encryption test PASSED

============================================================
  Initialization Complete!
============================================================
```

#### 4.2 Verify .env File

```bash
cat .env
```

**Should contain**:
```env
# Encryption key for API credentials (NEVER commit this to git!)
ENCRYPTION_KEY=gAAAAABh5K2xL3...

# Redis connection URL
REDIS_URL=redis://localhost:6379/0
```

#### 4.3 Backup .env File (CRITICAL!)

```bash
# Copy to secure location
sudo cp .env /root/.env.backup
sudo chmod 600 /root/.env.backup

# Create backup script
cat > /root/backup_env.sh << 'EOF'
#!/bin/bash
cp /var/www/Ashutosh_Chartink_Cilent-2/.env /root/.env.backup.$(date +%Y%m%d)
chmod 600 /root/.env.backup.*
EOF

chmod +x /root/backup_env.sh
```

---

### Step 5: Setup SSL with Let's Encrypt

#### 5.1 Make Setup Script Executable

```bash
cd /var/www/Ashutosh_Chartink_Cilent-2
chmod +x setup_letsencrypt.sh
```

#### 5.2 Run Automated SSL Setup

```bash
sudo bash setup_letsencrypt.sh trading.yourdomain.com your@email.com
```

**Replace**:
- `trading.yourdomain.com` with your actual domain
- `your@email.com` with your email

**Expected output**:
```
==========================================
  Let's Encrypt SSL Setup for Utho Cloud
==========================================

Domain: trading.yourdomain.com
Email: your@email.com

Continue with this configuration? (y/N): y

[1/7] Updating package list...
[2/7] Installing Certbot and nginx...
[3/7] Creating nginx configuration...
✅ nginx configuration created
[4/7] Testing nginx configuration...
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
[5/7] Obtaining SSL certificate from Let's Encrypt...
✅ SSL certificate obtained
[6/7] Starting nginx...
✅ nginx started
[7/7] Setting up auto-renewal...
✅ Auto-renewal configured

==========================================
  SSL Setup Complete!
==========================================
```

#### 5.3 Verify SSL Certificate

```bash
# Check certificate details
sudo certbot certificates

# Test auto-renewal (dry run)
sudo certbot renew --dry-run
```

#### 5.4 Verify nginx Configuration

```bash
# Test nginx config
sudo nginx -t

# Check nginx status
sudo systemctl status nginx

# View nginx config
cat /etc/nginx/sites-enabled/trading
```

---

### Step 6: Run Application (Initial Test)

#### 6.1 Manual Start (Test Mode)

```bash
cd /var/www/Ashutosh_Chartink_Cilent-2
source myvenv/bin/activate

# Start application
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Expected output**:
```
INFO:     Started server process
INFO:     Waiting for application startup.
🔐 Encryption enabled - API credentials will be encrypted
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
📅 Daily reset scheduler started (7 AM IST)
📅 Next daily reset scheduled for: 2026-02-04 07:00:00 IST
```

#### 6.2 Test in Another Terminal

```bash
# Open new SSH session
ssh root@134.195.138.91

# Test local endpoint
curl http://127.0.0.1:8000/

# Test HTTPS through nginx
curl https://trading.yourdomain.com/
```

#### 6.3 Access Dashboard

Open browser: `https://trading.yourdomain.com/?user_id=1`

**If you see the dashboard** ✅ - nginx and SSL are working!

#### 6.4 Stop Test Server

Press `Ctrl+C` in the terminal running uvicorn.

---

### Step 7: Setup systemd Service (Production)

#### 7.1 Create systemd Service File

```bash
sudo nano /etc/systemd/system/trading.service
```

**Paste this content**:
```ini
[Unit]
Description=AshAlgo Trading Application
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/var/www/Ashutosh_Chartink_Cilent-2
Environment="PATH=/var/www/Ashutosh_Chartink_Cilent-2/myvenv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/var/www/Ashutosh_Chartink_Cilent-2/myvenv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=trading

[Install]
WantedBy=multi-user.target
```

Save and exit: `Ctrl+X`, `Y`, `Enter`

#### 7.2 Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable trading

# Start service
sudo systemctl start trading

# Check status
sudo systemctl status trading
```

**Expected output**:
```
● trading.service - AshAlgo Trading Application
     Loaded: loaded (/etc/systemd/system/trading.service; enabled)
     Active: active (running) since Mon 2026-02-03 20:00:00 IST
   Main PID: 12345 (python)
      Tasks: 2
     CGroup: /system.slice/trading.service
             └─12345 python -m uvicorn app.main:app...

Feb 03 20:00:00 systemd[1]: Started AshAlgo Trading Application.
Feb 03 20:00:01 trading[12345]: 🔐 Encryption enabled
Feb 03 20:00:01 trading[12345]: 📅 Daily reset scheduler started
```

#### 7.3 Service Management Commands

```bash
# Start service
sudo systemctl start trading

# Stop service
sudo systemctl stop trading

# Restart service
sudo systemctl restart trading

# View logs
sudo journalctl -u trading -f

# View last 100 lines
sudo journalctl -u trading -n 100

# View logs since today
sudo journalctl -u trading --since today
```

---

### Step 8: Configure Application

#### 8.1 Access Dashboard

Open browser: `https://trading.yourdomain.com/?user_id=1`

#### 8.2 Enter Zerodha API Credentials

1. Click **Settings** (gear icon)
2. Enter **API Key** and **API Secret**
3. Click **Save Credentials**
4. Click **Connect to Zerodha**
5. Login to Zerodha and authorize
6. You'll be redirected back to dashboard

#### 8.3 Configure Alert Strategies

1. Click **Alert Configuration**
2. Add your Chartink alert strategies:
   - Alert Name
   - Entry price offset
   - Exit percentage
   - Stop loss
   - Trailing stop loss
3. Save each configuration

---

### Step 9: Configure Zerodha Webhook

#### 9.1 Get Webhook URL

Your webhook URL is:
```
https://trading.yourdomain.com/webhook/chartink?user_id=1
```

#### 9.2 Update Chartink

1. Go to Chartink.com
2. Open your scan/alert
3. Set webhook URL to above
4. Test webhook (send test alert)

#### 9.3 Verify Webhook Works

```bash
# Watch logs in real-time
sudo journalctl -u trading -f

# Send test webhook
curl -X POST https://trading.yourdomain.com/webhook/chartink?user_id=1 \
  -H "Content-Type: application/json" \
  -d '{"stocks":"RELIANCE,SBIN","alert_name":"Test Alert"}'

# Check dashboard - should see alert appear
```

---

### Step 10: Monitoring and Maintenance

#### 10.1 Setup Log Rotation

```bash
sudo nano /etc/logrotate.d/trading
```

**Paste**:
```
/var/log/trading/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        systemctl reload trading > /dev/null 2>&1 || true
    endscript
}
```

#### 10.2 Create Monitoring Script

```bash
cat > /root/monitor_trading.sh << 'EOF'
#!/bin/bash
# Check if trading service is running

if ! systemctl is-active --quiet trading; then
    echo "Trading service is down! Restarting..."
    systemctl restart trading
    # Optional: Send notification (email, Telegram, etc.)
fi

# Check Redis
if ! redis-cli ping > /dev/null 2>&1; then
    echo "Redis is down! Restarting..."
    systemctl restart redis-server
fi

# Check nginx
if ! systemctl is-active --quiet nginx; then
    echo "nginx is down! Restarting..."
    systemctl restart nginx
fi
EOF

chmod +x /root/monitor_trading.sh
```

#### 10.3 Add to Crontab

```bash
crontab -e
```

**Add**:
```cron
# Monitor trading app every 5 minutes
*/5 * * * * /root/monitor_trading.sh >> /var/log/trading_monitor.log 2>&1

# Backup .env daily at 2 AM
0 2 * * * /root/backup_env.sh

# Check SSL expiry weekly
0 0 * * 0 certbot renew --quiet
```

#### 10.4 View Application Metrics

```bash
# CPU and memory usage
ps aux | grep uvicorn

# Port binding
netstat -tulpn | grep :8000

# Redis memory usage
redis-cli INFO memory

# Disk usage
df -h
```

---

### Step 11: Daily Reset Verification

#### 11.1 Check Daily Reset Logs

```bash
# View tomorrow's scheduled reset time
sudo journalctl -u trading | grep "Next daily reset"

# After 7 AM, check reset logs
sudo journalctl -u trading --since "07:00" --until "07:05" | grep "DAILY RESET"
```

**Expected log output at 7 AM**:
```
============================================================
🔄 DAILY RESET STARTING at 2026-02-04 07:00:00 IST
============================================================
✅ Cleared 23 alert history keys
✅ Cleared 5 position keys
✅ Cleared 12 trade count keys
✅ Reset auto square-off status
✅ Cleared in-memory positions
✅ Broadcast reset notification to UI
============================================================
🎉 DAILY RESET COMPLETE
============================================================
📅 Next daily reset scheduled for: 2026-02-05 07:00:00 IST
```

#### 11.2 Manual Reset Test

```bash
# Test reset without waiting for 7 AM
curl -X POST https://trading.yourdomain.com/api/test-reset

# Check dashboard - should clear all alerts and positions
```

---

### Step 12: Updating Application

#### 12.1 Update Code

**From local machine**:
```powershell
# Upload updated files
scp app/main.py root@134.195.138.91:/var/www/Ashutosh_Chartink_Cilent-2/app/
```

**On server**:
```bash
# Restart service to apply changes
sudo systemctl restart trading

# Watch logs
sudo journalctl -u trading -f
```

#### 12.2 Update Dependencies

```bash
cd /var/www/Ashutosh_Chartink_Cilent-2
source myvenv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart trading
```

---

## 🔍 Troubleshooting

### Issue: Service Won't Start

```bash
# Check service status
sudo systemctl status trading

# View detailed logs
sudo journalctl -u trading -n 50 --no-pager

# Common fixes:
# 1. Check Python path
which python
# Should be: /var/www/Ashutosh_Chartink_Cilent-2/myvenv/bin/python

# 2. Check permissions
ls -la /var/www/Ashutosh_Chartink_Cilent-2

# 3. Test manually
cd /var/www/Ashutosh_Chartink_Cilent-2
source myvenv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Issue: SSL Certificate Errors

```bash
# Check certificate status
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Check nginx config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

### Issue: Redis Connection Failed

```bash
# Check Redis status
sudo systemctl status redis-server

# Start Redis
sudo systemctl start redis-server

# Test connection
redis-cli ping

# Check Redis logs
sudo journalctl -u redis-server -n 50
```

### Issue: Dashboard Not Loading

```bash
# Check nginx error logs
sudo tail -f /var/log/nginx/trading_error.log

# Check application logs
sudo journalctl -u trading -f

# Test nginx config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

### Issue: Webhook Not Receiving Alerts

```bash
# Test webhook manually
curl -X POST https://trading.yourdomain.com/webhook/chartink?user_id=1 \
  -H "Content-Type: application/json" \
  -d '{"stocks":"RELIANCE","alert_name":"test"}'

# Check logs
sudo journalctl -u trading -f | grep webhook

# Verify Chartink webhook URL is correct
# Should be: https://trading.yourdomain.com/webhook/chartink?user_id=1
```

---

## 📊 Performance Optimization

### Enable Redis Persistence

```bash
sudo nano /etc/redis/redis.conf
```

**Find and set**:
```
save 900 1
save 300 10
save 60 10000
appendonly yes
```

```bash
sudo systemctl restart redis-server
```

### Limit Redis Memory

```bash
sudo nano /etc/redis/redis.conf
```

**Add**:
```
maxmemory 256mb
maxmemory-policy allkeys-lru
```

### Enable nginx Caching

Already configured in `setup_letsencrypt.sh` nginx template.

---

## 🔒 Security Checklist

- ✅ SSH key-based authentication (disable password auth)
- ✅ Firewall enabled (ufw)
- ✅ SSL certificate installed and auto-renewing
- ✅ .env file secured (chmod 600)
- ✅ .env backed up to secure location
- ✅ Credentials encrypted in Redis
- ✅ nginx reverse proxy configured
- ✅ Security headers enabled
- ✅ Regular backups scheduled
- ✅ Monitoring in place

---

## 📞 Support

### Useful Commands Reference

```bash
# Service management
sudo systemctl status trading
sudo systemctl restart trading
sudo journalctl -u trading -f

# nginx management
sudo systemctl status nginx
sudo systemctl restart nginx
sudo nginx -t

# Redis management
sudo systemctl status redis-server
redis-cli ping
redis-cli KEYS "*"

# SSL certificate
sudo certbot certificates
sudo certbot renew

# Disk space
df -h

# Memory usage
free -h

# Process monitoring
htop
```

---

## ✅ Deployment Checklist

Before going live:

- [ ] DNS configured and propagated
- [ ] Firewall rules set (80, 443, 22)
- [ ] Redis installed and running
- [ ] Code uploaded to `/var/www/Ashutosh_Chartink_Cilent-2`
- [ ] Virtual environment created and activated
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Encryption initialized (`python init_encryption.py`)
- [ ] `.env` file backed up to secure location
- [ ] SSL certificate obtained (Let's Encrypt)
- [ ] nginx configured and running
- [ ] systemd service created and enabled
- [ ] Application accessible via HTTPS
- [ ] Zerodha credentials entered and connected
- [ ] Alert configurations set up
- [ ] Webhook URL configured in Chartink
- [ ] Test webhook received and processed
- [ ] Daily reset scheduler verified (check logs)
- [ ] Monitoring and log rotation configured
- [ ] Backup strategy implemented

---

**🎉 Congratulations!** Your trading application is now live on Utho Cloud with:
- ✅ HTTPS/SSL security
- ✅ Encrypted credentials
- ✅ Daily automatic reset at 7 AM
- ✅ Auto square-off at 3:20 PM
- ✅ Production-ready monitoring
- ✅ Auto-restart on failures

**Webhook URL**: `https://trading.yourdomain.com/webhook/chartink?user_id=1`

**Dashboard**: `https://trading.yourdomain.com/?user_id=1`
