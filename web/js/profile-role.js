(() => {
  const role = new URLSearchParams(window.location.search).get("role");
  if (role !== "consumer") return;

  document.body.dataset.role = "consumer";
  document.title = "账户资料｜小象避坑 ZOUBEACON";

  const brandName = document.querySelector(".topbar-brand-copy strong");
  const brandCode = document.querySelector(".topbar-brand-copy small");
  const heroEyebrow = document.querySelector(".hero .eyebrow");
  const heroCopy = document.querySelector(".hero-copy");
  if (brandName) brandName.textContent = "小象避坑";
  if (brandCode) brandCode.textContent = "ZOUBEACON";
  if (heroEyebrow) heroEyebrow.textContent = "小象避坑 / ZOUBEACON";
  if (heroCopy) heroCopy.textContent = "查看账户资料、安全设置和隐私边界。物件资料只在授权项目空间内使用。";

  const links = Array.from(document.querySelectorAll(".topbar-links a"));
  const consumerNav = [
    ["property-analysis.html", "分析物件"],
    ["projects.html?demo=1", "我的项目"],
    ["profile.html?role=consumer", "账户资料"],
    ["index.html", "小象数据"],
  ];
  links.forEach((link, index) => {
    const item = consumerNav[index];
    if (!item) return;
    link.href = item[0];
    link.textContent = item[1];
    link.toggleAttribute("aria-current", index === 2);
  });

  const accountLinks = Array.from(document.querySelectorAll(".account-action-link"));
  const consumerAccountNav = [
    ["property-analysis.html", "分析"],
    ["projects.html?demo=1", "项目"],
    ["index.html", "数据"],
  ];
  accountLinks.forEach((link, index) => {
    const item = consumerAccountNav[index];
    if (!item) return;
    link.href = item[0];
    link.textContent = item[1];
  });

  const title = document.querySelector("#accountTitle");
  if (title) title.dataset.loggedOutTitle = "登录后可以编辑小象避坑资料";
  const copy = document.querySelector("#accountCopy");
  if (copy) copy.dataset.loggedOutCopy = "未登录不能编辑资料。登录后可以继续查看自己的项目和报告。";
})();
