/* Finance Bot — Session Saver background service worker.

   Minimal — just handles extension installation.
*/

chrome.runtime.onInstalled.addListener(() => {
  console.log('Finance Bot Session Saver installed');
});
