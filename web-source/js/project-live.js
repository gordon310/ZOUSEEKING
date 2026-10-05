import { getValidAccessToken, getProject, listMyQueries, runQueryJob } from "./api-client.js?v=20261005-r68";

const params = new URL(window.location.href).searchParams;
const propertyId = params.get("property_id");
const queryId = params.get("query_id");
const key = params.get("key");
const panel = document.querySelector("#liveProject");
const gate = document.querySelector("#workspaceAccessGate");
const notice = document.querySelector("#liveProjectNotice");
const run = document.querySelector("#liveProjectRun");
const reload = document.querySelector("#liveProjectReload");
let selectedQuery = null;
let loading = false;
let loadVersion = 0;

function fact(label, value) {
  const group = document.createElement("div");
  const term = document.createElement("dt");
  const description = document.createElement("dd");
  term.textContent = label;
  description.textContent = value == null || value === "" ? "未提供" : String(value);
  group.append(term, description);
  document.querySelector("#liveProjectFacts").append(group);
}

export async function loadLiveProject() {
  if (loading) return;
  const version = ++loadVersion;
  const login = gate.querySelector("a");
  login.href = `profile.html?role=consumer&return_to=${encodeURIComponent(`project.html${window.location.search}`)}#accountPanel`;
  const token = await getValidAccessToken();
  if (version !== loadVersion) return;
  if (!token) { panel.hidden = true; gate.hidden = false; return; }
  gate.hidden = true;
  panel.hidden = false;
  run.hidden = true;
  document.querySelector("#liveProjectReport").hidden = true;
  document.querySelector("#liveProjectFacts").replaceChildren();
  document.querySelector("#liveProjectStatus").textContent = "";
  document.querySelector("#liveProjectProgress").textContent = "";
  document.querySelector("#liveQueryContext").textContent = "";
  selectedQuery = null;
  if (!propertyId && !queryId && !key) {
    document.querySelector("#liveProjectTitle").textContent = "请选择项目";
    notice.textContent = "请从“我的项目”选择要继续的记录。";
    reload.hidden = true;
    return;
  }
  loading = true;
  reload.disabled = true;
  notice.textContent = "正在读取项目……";
  try {
    const property = propertyId ? await getProject(propertyId, token) : null;
    const queries = await listMyQueries(token);
    if (version !== loadVersion) return;
    selectedQuery = queries.find((query) => queryId ? String(query.id) === queryId : key && query.query_key === key) || null;
    if (!property && !selectedQuery) {
      document.querySelector("#liveProjectTitle").textContent = "项目不可用";
      notice.textContent = "该查询未出现在最近任务列表中，请返回我的项目选择记录。";
      if (key) {
        const report = document.querySelector("#liveProjectReport");
        report.href = `report.html?key=${encodeURIComponent(key)}`;
        report.hidden = false;
      }
      return;
    }
    const location = selectedQuery ? [selectedQuery.prefecture, selectedQuery.city, selectedQuery.ward].filter(Boolean).join("") : "";
    document.querySelector("#liveProjectTitle").textContent = property?.project_name || `${location}・${selectedQuery.asset_type || "物件"}`;
    if (property) {
      fact("已保存地址", property.address_normalized);
      fact("提交售价（JPY）", property.asking_price == null ? null : Number(property.asking_price).toLocaleString("zh-CN"));
      fact("提交面积（平方米）", property.area_sqm);
      fact("资料状态", "用户提交资料，待核验");
    }
    if (selectedQuery) {
      const job = selectedQuery.generation_jobs?.[0];
      const status = ["completed", "failed"].includes(selectedQuery.status) ? selectedQuery.status : job?.status || selectedQuery.status;
      const labels = { completed: "完整报告", failed: "生成失败", running: "生成中", pending: "待处理" };
      document.querySelector("#liveProjectStatus").textContent = labels[status] || "待处理";
      document.querySelector("#liveQueryContext").textContent = `区域查询：${location} · ${selectedQuery.asset_type || "未提供类型"}${selectedQuery.year && selectedQuery.month ? ` · ${selectedQuery.year}年${selectedQuery.month}月` : ""}`;
      document.querySelector("#liveProjectProgress").textContent = job?.progress == null ? "任务进度：未提供" : `任务进度：${Math.max(0, Math.min(100, Number(job.progress)))}%`;
      notice.textContent = status === "failed" ? "本次报告生成失败。可以重新生成；如仍失败，请联系支持。" : status === "running" ? "报告正在生成，可刷新查看状态。" : "";
      run.hidden = !selectedQuery.id || !["pending", "failed"].includes(status);
      run.textContent = status === "failed" ? "重新生成" : "生成报告";
      const report = document.querySelector("#liveProjectReport");
      report.hidden = status !== "completed" || !selectedQuery.query_key;
      if (!report.hidden) report.href = `report.html?key=${encodeURIComponent(selectedQuery.query_key)}`;
    } else {
      notice.textContent = "物件资料已保存；对应查询未出现在最近任务列表中。";
      if (key) {
        const report = document.querySelector("#liveProjectReport");
        report.href = `report.html?key=${encodeURIComponent(key)}`;
        report.hidden = false;
      }
    }
  } catch (error) {
    if (version !== loadVersion) return;
    if (error.status === 401 || error.status === 403) {
      panel.hidden = true;
      gate.hidden = false;
    } else {
      document.querySelector("#liveProjectTitle").textContent = "项目暂时不可用";
      notice.textContent = error.status === 404 ? "项目不存在或无权访问，请返回我的项目。" : "项目暂时无法读取，请重新读取。";
      reload.textContent = "重新读取";
    }
  } finally {
    if (version === loadVersion) {
      loading = false;
      reload.disabled = false;
    }
  }
}

reload.addEventListener("click", loadLiveProject);
run.addEventListener("click", async () => {
  if (!selectedQuery?.id || run.disabled) return;
  run.disabled = true;
  reload.disabled = true;
  try {
    const token = await getValidAccessToken();
    if (!token) { await loadLiveProject(); return; }
    await runQueryJob(selectedQuery.id, token);
    await loadLiveProject();
  } catch {
    notice.textContent = "报告暂时无法生成，请重新读取状态后再试；如仍失败，请联系支持。";
  } finally {
    run.disabled = false;
    reload.disabled = false;
  }
});
window.addEventListener("zou-auth-session-changed", () => {
  if (params.get("demo") === "1") return;
  loadVersion += 1;
  loading = false;
  panel.hidden = true;
  gate.hidden = false;
  loadLiveProject();
});
