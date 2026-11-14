// Random page titles for the multistream view. The HTML <title> defaults to
// "screenshare" (what no-JS visitors see); with JS, one of these is picked at
// random on each page load. Add more phrases to the list below.
(function () {
  var titles = [
    "watch party",
  ];
  if (titles.length) {
    document.title = titles[Math.floor(Math.random() * titles.length)];
  }
})();
