const views = { list: document.querySelector('#listView'), form: document.querySelector('#formView'), detail: document.querySelector('#detailView') };
const form = document.querySelector('#orderForm');
let orders = [];

const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const date = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : 'Não informada';
const money = value => value === null || value === '' ? 'Não informado' : Number(value).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});
const info = (label, value, wide = false) => `<div class="info-item ${wide ? 'wide' : ''}"><small>${label}</small><p>${esc(value || 'Não informado')}</p></div>`;
const marked = value => esc(value || 'Nenhum item marcado');

function show(name) {
  Object.entries(views).forEach(([key, node]) => node.classList.toggle('hidden', key !== name));
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function loadOrders() {
  const response = await fetch('/api/orders');
  orders = await response.json();
  renderList();
}

function renderList() {
  const query = document.querySelector('#searchInput').value.toLowerCase().trim();
  const status = document.querySelector('#statusFilter').value;
  const filtered = orders.filter(order => {
    const haystack = `${order.number} ${order.customer_name} ${order.device_type} ${order.brand} ${order.model}`.toLowerCase();
    return (!query || haystack.includes(query)) && (!status || order.status === status);
  });
  document.querySelector('#totalCount').textContent = orders.length;
  document.querySelector('#openCount').textContent = orders.filter(o => !['Entregue','Cancelado'].includes(o.status)).length;
  document.querySelector('#doneCount').textContent = orders.filter(o => o.status === 'Entregue').length;
  document.querySelector('#ordersList').innerHTML = filtered.map(order => `
    <article class="order-row" data-id="${order.id}">
      <div><span class="order-number">${order.number}</span><small>${date(order.entry_date)}</small></div>
      <div><strong>${esc(order.customer_name)}</strong><small>${esc(order.phone || order.email || 'Sem contato')}</small></div>
      <div><strong>${esc(order.device_type)}</strong><small>${esc([order.brand, order.model].filter(Boolean).join(' · ') || 'Sem marca/modelo')}</small></div>
      <span class="status" data-status="${esc(order.status)}">${esc(order.status)}</span><b>›</b>
    </article>`).join('');
  document.querySelector('#emptyState').classList.toggle('hidden', filtered.length !== 0);
  document.querySelectorAll('.order-row').forEach(row => row.onclick = () => openDetail(Number(row.dataset.id)));
}

function newOrder() {
  form.reset();
  form.orderId.value = '';
  form.entry_date.value = new Date().toISOString().slice(0, 10);
  document.querySelector('#formEyebrow').textContent = 'NOVA ORDEM';
  document.querySelector('#formTitle').textContent = 'Cadastrar ordem de serviço';
  document.querySelector('#saveButton').textContent = 'Salvar e gerar número';
  show('form');
}

function editOrder(id) {
  const order = orders.find(item => item.id === id);
  if (!order) return;
  form.reset();
  form.orderId.value = id;
  [...form.elements].forEach(field => {
    if (!field.name || order[field.name] == null) return;
    if (field.type === 'checkbox') field.checked = String(order[field.name]).split(', ').includes(field.value);
    else field.value = order[field.name];
  });
  document.querySelector('#formEyebrow').textContent = order.number;
  document.querySelector('#formTitle').textContent = 'Editar ordem de serviço';
  document.querySelector('#saveButton').textContent = 'Salvar alterações';
  show('form');
}

function openDetail(id) {
  const o = orders.find(item => item.id === id);
  if (!o) return;
  views.detail.innerHTML = `<div class="screen-detail">
    <div class="detail-head"><div class="detail-head-left"><button class="back" data-back>←</button><div><p class="eyebrow">${esc(o.service_kind || 'ORDEM DE SERVIÇO')}</p><div class="order-big">${o.number}</div></div></div><div class="detail-actions"><button class="secondary" id="editDetail">Editar</button><button class="primary" id="printDetail">Imprimir 2 vias</button></div></div>
    <div class="detail-grid"><div>
      <div class="detail-card"><h2>Cliente</h2><div class="info-grid">${info('Nome completo',o.customer_name)}${info('CPF',o.cpf)}${info('Telefone',o.phone)}${info('E-mail',o.email)}${info('Endereço',o.address,true)}</div></div>
      <div class="detail-card" style="margin-top:16px"><h2>Aparelho e atendimento</h2><div class="info-grid">${info('Aparelho',o.device_type)}${info('Marca / modelo',[o.brand,o.model].filter(Boolean).join(' / '))}${info('Cor / capacidade',[o.color,o.capacity].filter(Boolean).join(' / '))}${info('IMEI / série',o.serial_number)}${info('Senha / padrão',o.unlock_password)}${info('Conta removida',o.account_removed)}${info('Estado na entrada',o.device_condition,true)}${info('Acessórios',o.accessories,true)}${info('Checklist técnico',o.technical_checklist,true)}${info('Defeito relatado',o.reported_issue,true)}${info('Laudo técnico',o.technical_report,true)}${info('Observações',o.notes,true)}</div></div>
    </div><aside class="detail-card"><h2>Resumo da OS</h2><div class="info-grid" style="grid-template-columns:1fr">${info('Status',o.status)}${info('Entrada',date(o.entry_date))}${info('Previsão de entrega',date(o.delivery_date))}${info('Garantia até',date(o.warranty_until))}${info('Valor aprovado',money(o.estimated_value))}${info('Pagamento',o.payment_method)}${info('Responsável técnico',o.technician)}${info('Retirado por',o.picked_up_by)}${info('Data da retirada',date(o.pickup_date))}</div></aside></div></div>
    <div class="print-sheet">${printableCopy(o,'VIA DA EMPRESA')}${printableCopy(o,'VIA DO CLIENTE')}</div>`;
  views.detail.querySelector('[data-back]').onclick = () => show('list');
  views.detail.querySelector('#editDetail').onclick = () => editOrder(id);
  views.detail.querySelector('#printDetail').onclick = () => window.print();
  show('detail');
}

function printableCopy(o, copyLabel) {
  const line = (label, value) => `<div class="p-field"><b>${label}</b><span>${esc(value || '—')}</span></div>`;
  return `<section class="print-copy">
    <header class="p-head"><div><strong>OS DIGITAL</strong><small>Assistência técnica</small></div><div class="p-number"><small>${esc(o.service_kind || 'ORDEM DE SERVIÇO')} · ${copyLabel}</small><b>${o.number}</b></div></header>
    <div class="p-strip"><b>Entrada:</b> ${date(o.entry_date)} <b>Entrega:</b> ${date(o.delivery_date)} <b>Garantia:</b> ${date(o.warranty_until)} <b>Status:</b> ${esc(o.status)}</div>
    <h3>1. DADOS DO CLIENTE</h3><div class="p-grid p4">${line('Nome completo',o.customer_name)}${line('CPF',o.cpf)}${line('Telefone',o.phone)}${line('E-mail',o.email)}</div>${line('Endereço',o.address)}
    <h3>2. DADOS DO APARELHO</h3><div class="p-grid p5">${line('Aparelho',o.device_type)}${line('Marca',o.brand)}${line('Modelo',o.model)}${line('Cor',o.color)}${line('Capacidade',o.capacity)}</div><div class="p-grid p3">${line('IMEI / Série',o.serial_number)}${line('Senha / padrão',o.unlock_password)}${line('Conta removida',o.account_removed)}</div>
    <div class="p-grid p3 blocks"><div><h3>3. DEFEITO INFORMADO</h3><p>${esc(o.reported_issue)}</p></div><div><h3>4. ESTADO NA ENTRADA</h3><p>${marked(o.device_condition)}</p></div><div><h3>5. ACESSÓRIOS</h3><p>${marked(o.accessories)}</p></div></div>
    <h3>6. CHECKLIST TÉCNICO</h3><p class="p-check">${marked(o.technical_checklist)}</p>
    <div class="p-grid p2 notes"><div><b>Laudo / observações técnicas:</b><p>${esc(o.technical_report || o.notes || '—')}</p></div><div><b>Valor aprovado:</b> ${money(o.estimated_value)}<br><b>Pagamento:</b> ${esc(o.payment_method || '—')}</div></div>
    <div class="p-warning">TELA TRINCADA, OXIDAÇÃO E DANOS FÍSICOS NÃO SÃO COBERTOS PELA GARANTIA.</div>
    <p class="p-terms">Declaro verdadeiras as informações acima e autorizo o diagnóstico e os serviços aprovados. A garantia cobre somente o serviço e as peças descritas nesta OS; não cobre quedas, líquidos, oxidação, mau uso, dados ou acessórios deixados no aparelho. Equipamentos não retirados poderão estar sujeitos a taxa de armazenamento.</p>
    <div class="p-grid p4 signatures">${line('Responsável técnico',o.technician)}${line('Recebido por',o.received_by)}${line('Retirado por / CPF',[o.picked_up_by,o.pickup_cpf].filter(Boolean).join(' · '))}${line('Assinatura do cliente','')}</div>
  </section>`;
}

form.onsubmit = async event => {
  event.preventDefault();
  const id = form.orderId.value;
  const data = new FormData(form);
  const payload = Object.fromEntries(data.entries());
  ['device_condition','accessories','technical_checklist'].forEach(name => payload[name] = data.getAll(name).join(', '));
  const response = await fetch(id ? `/api/orders/${id}` : '/api/orders', {method: id ? 'PUT' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) return toast(result.error || 'Não foi possível salvar a OS.');
  await loadOrders();
  toast(id ? 'Alterações salvas.' : `${result.number} criada com sucesso.`);
  openDetail(result.id);
};

function toast(message) {
  const node = document.querySelector('#toast');
  node.textContent = message; node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 3000);
}

document.querySelector('#newOrder').onclick = newOrder;
document.querySelector('#emptyNew').onclick = newOrder;
document.querySelectorAll('[data-back]').forEach(button => button.onclick = () => show('list'));
document.querySelector('#searchInput').oninput = renderList;
document.querySelector('#statusFilter').onchange = renderList;
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    if (!views.list.classList.contains('hidden')) document.querySelector('#searchInput').focus();
  }
});
loadOrders().catch(() => toast('Não foi possível carregar as ordens.'));
