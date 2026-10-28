// node render.js card.html card.png: screenshot the SGP card at 2x for Discord.
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const [src, out] = process.argv.slice(2);
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2 });
  await page.goto('file://' + path.resolve(src));
  await (await page.$('.c')).screenshot({ path: out });
  await browser.close();
})();
