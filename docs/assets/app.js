const pages=[
  ["overview","00","Overview","index.html","Purpose, guarantees, and chapters"],
  ["architecture","01","Architecture","architecture.html","Components, data flow, and trust boundaries"],
  ["workflows","02","Workflow atlas","workflows.html","GitHub Actions and observable hand-offs"],
  ["content","03","Lesson studio","content-studio.html","German pedagogy and content contracts"],
  ["media","04","Media engine","media-engine.html","Chatterbox voice, visuals, thumbnails, and assembly"],
  ["approvals","05","Approval & publishing","approvals.html","Commands, retries, states, and schedule policy"],
  ["limits","06","Costs & limits","limits.html","Quotas, throttles, and capacity"],
  ["operations","07","Operator recipes","operations.html","Setup, recovery, and analytics"]
];
const currentPage=document.body.dataset.page;
const navHost=document.querySelector("[data-site-nav]");
if(navHost)navHost.innerHTML=`<a class="site-brand" href="index.html"><span class="brand-mark">T</span><span><strong>Talkivana</strong><small>Automation field guide</small></span></a><p class="nav-label">Chapters</p><nav class="site-nav">${pages.map(([id,n,label,href])=>`<a href="${href}" ${id===currentPage?'aria-current="page"':""}><span>${n}</span>${label}</a>`).join("")}</nav><div class="sidebar-tools"><button type="button" data-command-open>Quick find</button><button type="button" data-theme-toggle aria-label="Toggle color theme">Light</button></div>`;
const footerHost=document.querySelector("[data-site-footer]");
if(footerHost){footerHost.className="page-footer";footerHost.innerHTML=`<span>Talkivana Automation · operational documentation</span><span><a href="privacy.html">Privacy</a> · <a href="https://github.com/Indusvalley7/talkivana-automation">Source repository</a></span>`}
const root=document.documentElement,themeButton=document.querySelector("[data-theme-toggle]"),savedTheme=localStorage.getItem("talkivana-theme");
if(savedTheme)root.dataset.theme=savedTheme;
function syncThemeLabel(){if(themeButton)themeButton.textContent=root.dataset.theme==="dark"?"Light":"Dark"}syncThemeLabel();
themeButton?.addEventListener("click",()=>{root.dataset.theme=root.dataset.theme==="dark"?"light":"dark";localStorage.setItem("talkivana-theme",root.dataset.theme);syncThemeLabel()});
const sidebar=document.querySelector(".sidebar"),menuToggle=document.querySelector("[data-menu-toggle]");
menuToggle?.addEventListener("click",()=>{const open=sidebar?.classList.toggle("is-open");menuToggle.setAttribute("aria-expanded",String(Boolean(open)))});
document.querySelectorAll("[data-copy]").forEach(button=>button.addEventListener("click",async()=>{await navigator.clipboard.writeText(button.dataset.copy||"");const label=button.querySelector("span");if(label){label.textContent="copied";setTimeout(()=>label.textContent="copy",1200)}}));
if(!document.querySelector("[data-command-dialog]"))document.body.insertAdjacentHTML("beforeend",`<div class="command-dialog" data-command-dialog hidden><div class="command-backdrop" data-command-close></div><div class="command-panel" role="dialog" aria-modal="true" aria-label="Quick navigation"><div class="command-input-row"><span>⌕</span><input data-command-input type="search" placeholder="Find architecture, Chatterbox, retry…" autocomplete="off"><kbd>esc</kbd></div><div class="command-results" data-command-results></div></div></div>`);
const dialog=document.querySelector("[data-command-dialog]"),searchInput=document.querySelector("[data-command-input]"),results=document.querySelector("[data-command-results]");
function renderResults(query=""){if(!results)return;const term=query.trim().toLowerCase(),matches=pages.filter(page=>!term||page.join(" ").toLowerCase().includes(term));results.innerHTML=matches.map(([,n,label,href,description])=>`<a class="command-result" href="${href}"><span>${n}</span><span><strong>${label}</strong><small>${description}</small></span></a>`).join("")||`<p style="padding:18px;color:#829995">No chapter found. Try “voice”, “limit”, or “approval”.</p>`}
function openDialog(){if(!dialog)return;dialog.hidden=false;renderResults();setTimeout(()=>searchInput?.focus(),0)}function closeDialog(){if(dialog)dialog.hidden=true}
document.querySelectorAll("[data-command-open]").forEach(button=>button.addEventListener("click",openDialog));document.querySelector("[data-command-close]")?.addEventListener("click",closeDialog);searchInput?.addEventListener("input",event=>renderResults(event.target.value));
document.addEventListener("keydown",event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==="k"){event.preventDefault();openDialog()}if(event.key==="Escape")closeDialog();if(event.key==="/"&&document.activeElement?.tagName!=="INPUT"){event.preventDefault();openDialog()}});
const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add("is-visible");observer.unobserve(entry.target)}}),{threshold:.08});document.querySelectorAll(".reveal").forEach(element=>observer.observe(element));
