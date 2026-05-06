(function (window) {
  const helpers = {
    on(element, event, handler) {
      if (element) {
        element.addEventListener(event, handler);
      }
    },
    escapeHtml(value = "") {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },
  };

  window.AppHelpers = helpers;
})(window);
