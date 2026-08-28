(() => {
  const filter = document.querySelector("#businessTaskFilter");
  const message = document.querySelector("#businessTaskMessage");
  const cards = Array.from(document.querySelectorAll("[data-service-task]"));

  function setMessage(text) {
    if (message) message.textContent = text;
  }

  function renderTasks() {
    const selected = filter?.value || "all";
    cards.forEach((card) => {
      card.classList.toggle("is-hidden", selected !== "all" && card.dataset.taskStatus !== selected);
    });
  }

  function markAssigned(card, button) {
    card.dataset.taskStatus = "进行中";
    const status = card.querySelector(".service-task-status");
    if (status) {
      status.className = "service-task-status status-active";
      status.textContent = "进行中";
    }
    const owner = card.querySelector(".service-task-footer span");
    if (owner) owner.textContent = "已分配给当前工作台";
    button.classList.add("secondary-action");
    button.disabled = true;
    button.textContent = "已接单（演示）";
    setMessage("任务已在本地演示状态中标记为进行中；未创建真实订单。" );
    renderTasks();
  }

  filter?.addEventListener("change", renderTasks);
  document.querySelectorAll("[data-business-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest("[data-service-task]");
      if (!card) return;
      if (button.dataset.businessAction === "assign") {
        markAssigned(card, button);
        return;
      }
      const title = card.querySelector("h3")?.textContent || "服务任务";
      setMessage(`已打开「${title}」的演示详情；真实任务详情待后端接入。`);
    });
  });

  renderTasks();
})();
