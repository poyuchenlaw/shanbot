const path = require('path');

module.exports = {
  apps: [
    {
      name: 'shanbot',
      script: '/usr/local/bin/uvicorn',
      args: 'main:app --host 0.0.0.0 --port 8025',
      cwd: __dirname,
      interpreter: 'python3',
      env: {
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: __dirname,
      },
      max_restarts: 10,
      restart_delay: 3000,
      max_memory_restart: '400M',
      error_file: path.join(__dirname, 'logs', 'error.log'),
      out_file: path.join(__dirname, 'logs', 'out.log'),
    },
    {
      name: 'shanbot-watchdog',
      script: 'tools/watchdog.py',
      cwd: __dirname,
      interpreter: 'python3',
      cron_restart: '0 9 * * *',
      autorestart: false,
      env: {
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: __dirname,
        // Simon 本人 LINE userId（reconcile 時確認所有公司 pending 都對到這個 ID）
        SHANBOT_ADMIN_LINE_ID: 'U2a551ae0489009eb31a864860504b804',
      },
      error_file: path.join(__dirname, 'logs', 'watchdog.err.log'),
      out_file: path.join(__dirname, 'logs', 'watchdog.out.log'),
    },
  ],
};
