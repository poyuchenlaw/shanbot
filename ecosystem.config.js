module.exports = {
  apps: [{
    name: 'shanbot',
    script: '/usr/local/bin/uvicorn',
    args: 'main:app --host 0.0.0.0 --port 8025',
    cwd: '/home/simon/shanbot',
    interpreter: 'python3',
    env: {
      PYTHONUNBUFFERED: '1',
      PYTHONPATH: '/home/simon/shanbot',
    },
    max_restarts: 10,
    restart_delay: 3000,
    max_memory_restart: '400M',
    error_file: '/home/simon/shanbot/logs/error.log',
    out_file: '/home/simon/shanbot/logs/out.log',
  }],
};
