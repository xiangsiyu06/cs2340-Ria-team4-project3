const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:8000', channel: 'chrome' },
  webServer: {
    command: '.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload --settings=devpreview.settings',
    url: 'http://127.0.0.1:8000',
    reuseExistingServer: !process.env.CI,
  },
});
