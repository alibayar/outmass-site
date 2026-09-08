// Browser-aware store CTAs: the site defaults to Chrome everywhere; when the
// visitor is on desktop Edge (UA "Edg/"), point store links at the Edge
// Add-ons listing and flip the "also available" cross-link to Chrome.
// Collect both link sets BEFORE mutating — after the first swap the two
// selectors would otherwise match each other's results.
(function () {
  if (!/Edg\//.test(navigator.userAgent)) return;

  var CHROME_URL = "https://chromewebstore.google.com/detail/outmass/adcfddainnkjomddlappnnbeomhlcbmm";
  var EDGE_URL = "https://microsoftedge.microsoft.com/addons/detail/nfgnhhdeninjmnpfbhnggknimhejbelc";

  var chromeLinks = Array.prototype.slice.call(
    document.querySelectorAll('a[href^="https://chromewebstore.google.com"]')
  );
  var edgeLinks = Array.prototype.slice.call(
    document.querySelectorAll('a[href^="https://microsoftedge.microsoft.com"]')
  );

  chromeLinks.forEach(function (a) {
    a.href = EDGE_URL;
    a.textContent = a.textContent
      .replace("Add to Chrome", "Add to Edge")
      .replace("Chrome Web Store", "Edge Add-ons store");
  });

  edgeLinks.forEach(function (a) {
    a.href = CHROME_URL;
    a.textContent = a.textContent.replace("Microsoft Edge", "Google Chrome");
  });
})();
