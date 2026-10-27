// Where the API is. On GitHub Pages the pages call the Cloud Run service by its full URL. When the service serves the
// site itself (the MVP at its own URL), calls are same-origin. Override for local work with ?api=http://localhost:8080
const onPages = location.hostname.endsWith("github.io");
window.AEGIS = {
  api: onPages ? "https://aegis-api-335536436651.us-central1.run.app" : "",
  help: onPages ? "../help/" : "https://siddharthraop.github.io/AEGIS/help/",
};
