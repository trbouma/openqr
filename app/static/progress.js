// Keep native form submission and validation, adding only pending-state feedback.
document.querySelectorAll("form[data-progress]").forEach((form) => {
  const status = document.getElementById(form.dataset.progress);
  const message = status.querySelector("[data-progress-message]");
  const spinner = status.querySelector(".progress-spinner");
  let pending = false;
  let disabledButtons = [];

  form.addEventListener("submit", (event) => {
    if (pending) {
      event.preventDefault();
      return;
    }
    if (event.defaultPrevented) return;
    pending = true;
    form.setAttribute("aria-busy", "true");
    message.textContent = message.dataset.progressMessage;
    spinner.hidden = false;
    // Leave the named inputs enabled so the browser includes them in the request.
    disabledButtons = [...form.querySelectorAll('button[type="submit"]')]
      .filter((button) => !button.disabled);
    disabledButtons.forEach((button) => { button.disabled = true; });
  });

  window.addEventListener("pageshow", () => {
    pending = false;
    form.removeAttribute("aria-busy");
    message.textContent = "";
    spinner.hidden = true;
    disabledButtons.forEach((button) => { button.disabled = false; });
    disabledButtons = [];
  });
});
