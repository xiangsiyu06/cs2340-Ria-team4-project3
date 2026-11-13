const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  use: { channel: 'chrome' },
  projects: [
    { name: 'preview', testMatch: 'chat.spec.js', use: { baseURL: 'http://127.0.0.1:8003' } },
    { name: 'integrated', testMatch: 'integrated.spec.js', use: { baseURL: 'http://127.0.0.1:8002' } },
  ],
  webServer: [{
    command: '.venv/bin/python manage.py runserver 127.0.0.1:8003 --noreload --settings=devpreview.settings',
    url: 'http://127.0.0.1:8003',
    reuseExistingServer: false,
  }, {
    command: '.venv/bin/python manage.py runserver 127.0.0.1:8002 --noreload',
    env: { DEBUG: 'True', ALLOWED_HOSTS: '127.0.0.1,localhost' },
    url: 'http://127.0.0.1:8002/chat/',
    reuseExistingServer: false,
  }],
});
