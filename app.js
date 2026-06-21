const views = { list: document.querySelector('#listView'), form: document.querySelector('#formView'), detail: document.querySelector('#detailView') };
const form = document.querySelector('#orderForm');
let orders = [];

const localHost = ['127.0.0.1', 'localhost'].includes(location.hostname);
const HOSTED_MODE = location.hostname.endsWith('.vercel.app');
const STORAGE_KEY = 'os-digital-orders-v1';
if (location.protocol === 'file:' || (localHost && location.port !== '8000')) {
  location.replace('http://127.0.0.1:8000');
}

const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const date = value => value ? new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR') : 'Não informada';
const money = value => value === null || value === '' ? 'Não informado' : Number(value).toLocaleString('pt-BR', {style:'currency', currency:'BRL'});
const info = (label, value, wide = false) => `<div class="info-item ${wide ? 'wide' : ''}"><small>${label}</small><p>${esc(value || 'Não informado')}</p></div>`;
const marked = value => esc(value || 'Nenhum item marcado');
const LEGAL_TERMS = [
  'Toda troca de peças ou manutenção em aparelhos eletrônicos tem garantia de 90 (noventa) dias, a contar da data de entrega do serviço.',
  'Procedimento de banho químico por si só não tem garantia, entrando somente na garantia as peças que forem trocadas junto com o serviço de banho químico.',
  'Nos procedimentos de banho químico é de conhecimento do cliente que o aparelho, caso esteja ligando e/ou funcionando parcialmente, pode parar de funcionar e/ou responder sem aviso ou intervenção técnica, não sendo a loja responsável por esses acontecimentos.',
  'A garantia exclui totalmente danos causados por mau uso, incluindo quedas, arranhões e/ou amassados.',
  'Devido à escassez de peças e dificuldade de importação, os retornos podem demorar até 2 dias úteis para serem atendidos.',
  'Orçamento e/ou procedimento de banho químico: o prazo para retorno ao cliente é de 3 a 4 dias úteis.',
  'Teste seu aparelho na entrega, pois não nos responsabilizamos por defeitos diferentes dos especificados na ordem de serviço.',
  'Não nos responsabilizamos por chips, cartões de memória, capas, películas ou quaisquer acessórios deixados no aparelho. Em caso de extravio, não haverá qualquer ressarcimento.',
  'A Buzz Tech não realiza backup de dados e não se responsabiliza pela perda de fotos, vídeos, documentos, aplicativos, contas ou quaisquer informações armazenadas no aparelho.',
  'Aparelhos que ingressarem na assistência sem imagem, sem ligar ou sem possibilidade de teste terão garantia limitada aos serviços efetivamente executados, não abrangendo componentes que não puderem ser testados previamente.',
  'Equipamentos abandonados: após 90 dias da comunicação de conclusão do serviço, poderão ser cobradas taxas de armazenamento conforme legislação aplicável, ficando o aparelho disponível para resgate mediante pagamento.',
  'A aprovação verbal, por mensagem, ligação telefônica, WhatsApp ou qualquer meio eletrônico autoriza a execução do orçamento e dos serviços descritos nesta Ordem de Serviço/Garantia.',
  'Aparelhos com histórico de queda, oxidação, contato com líquidos, superaquecimento, tentativas anteriores de reparo ou danos estruturais podem apresentar falhas adicionais ou tornar-se irrecuperáveis durante o processo técnico.',
  'Serviços realizados em aparelhos Apple ou Android poderão afetar funcionalidades biométricas já comprometidas anteriormente. Não garantimos recuperação de Face ID, Touch ID ou biometria quando houver defeito pré-existente.',
  'Equipamentos que apresentam cola solta, tela descolando, carcaça empenada ou estrutura comprometida poderão sofrer agravamento dos danos durante o reparo, não caracterizando falha na execução do serviço.',
  'Em aparelhos com oxidação ou contato com líquidos não há garantia sobre recuperação de dados ou funcionamento futuro, ainda que o aparelho volte a funcionar após o reparo.',
  'Orçamentos aprovados autorizam a execução integral do serviço descrito nesta Ordem de Serviço/Garantia.',
  'A garantia concedida pela Buzz Tech cobre exclusivamente defeitos de funcionamento relacionados ao produto ou serviço descrito nesta OS. Não cobre quedas, impactos, líquidos, oxidação, mau uso, tentativa de reparo por terceiros, violação de lacres ou danos estéticos.'
];
const CLIENT_DECLARATION = 'Declaro que as informações fornecidas nesta Ordem de Serviço são verdadeiras e autorizo a Buzz Tech Assistência Técnica a realizar os procedimentos necessários para diagnóstico, orçamento e reparo do equipamento descrito neste documento.';

function show(name) {
  Object.entries(views).forEach(([key, node]) => node.classList.toggle('hidden', key !== name));
  window.scrollTo({top: 0, behavior: 'smooth'});
}

async function loadOrders() {
  if (HOSTED_MODE) {
    orders = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    renderList();
    return;
  }
  const response = await fetch('/api/orders');
  orders = await responseJson(response);
  renderList();
}

async function responseJson(response) {
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); }
  catch { throw new Error('O servidor da OS não respondeu corretamente. Execute iniciar.bat novamente.'); }
  if (!response.ok) throw new Error(data.error || 'Falha na comunicação com o servidor.');
  return data;
}

async function checkServer() {
  const status = document.querySelector('#systemStatus');
  if (HOSTED_MODE) {
    status.className = 'system-live is-online';
    status.querySelector('span').textContent = 'Salvo neste dispositivo';
    return;
  }
  try {
    const response = await fetch('/api/health', {cache:'no-store'});
    await responseJson(response);
    status.className = 'system-live is-online';
    status.querySelector('span').textContent = 'Sistema online';
  } catch {
    status.className = 'system-live is-offline';
    status.querySelector('span').textContent = 'Servidor desconectado';
  }
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
  document.querySelector('#orderId').value = '';
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
  document.querySelector('#orderId').value = id;
  [...form.elements].forEach(field => {
    if (!field.name || order[field.name] == null) return;
    if (field.type === 'checkbox') field.checked = String(order[field.name]).split(', ').includes(field.value);
    else field.value = order[field.name];
  });
  const valueField = form.elements.estimated_value;
  if (valueField.value) valueField.value = Number(valueField.value).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
  form.elements.cpf.value = cpfMask(form.elements.cpf.value);
  form.elements.pickup_cpf.value = cpfMask(form.elements.pickup_cpf.value);
  document.querySelector('#formEyebrow').textContent = order.number;
  document.querySelector('#formTitle').textContent = 'Editar ordem de serviço';
  document.querySelector('#saveButton').textContent = 'Salvar alterações';
  show('form');
}

function openDetail(id) {
  const o = orders.find(item => item.id === id);
  if (!o) return;
  views.detail.innerHTML = `<div class="screen-detail">
    <div class="detail-head"><div class="detail-head-left"><button class="back" data-back>←</button><div><p class="eyebrow">${esc(o.service_kind || 'ORDEM DE SERVIÇO')}</p><div class="order-big">${o.number}</div></div></div><div class="detail-actions"><button class="secondary" id="editDetail">Editar</button><button class="secondary" id="storePdf">Via da loja</button><button class="secondary" id="techPdf">Imprimir técnico</button><button class="secondary whatsapp" id="clientDigital">WhatsApp cliente</button><button class="primary" id="printDetail">Imprimir 2 vias</button></div></div>
    <div class="detail-grid"><div>
      <div class="detail-card"><h2>Cliente</h2><div class="info-grid">${info('Nome completo',o.customer_name)}${info('CPF',o.cpf)}${info('Telefone',o.phone)}${info('E-mail',o.email)}${info('Endereço',o.address,true)}</div></div>
      <div class="detail-card" style="margin-top:16px"><h2>Aparelho e atendimento</h2><div class="info-grid">${info('Aparelho',o.device_type)}${info('Marca / modelo',[o.brand,o.model].filter(Boolean).join(' / '))}${info('Cor / capacidade',[o.color,o.capacity].filter(Boolean).join(' / '))}${info('IMEI / série',o.serial_number)}${info('Senha / padrão',o.unlock_password)}${info('Conta removida',o.account_removed)}${info('Estado na entrada',o.device_condition,true)}${info('Acessórios',o.accessories,true)}${info('Checklist técnico',o.technical_checklist,true)}${info('Defeito relatado',o.reported_issue,true)}${info('Laudo técnico',o.technical_report,true)}${info('Observações',o.notes,true)}</div></div>
    </div><aside class="detail-card"><h2>Resumo da OS</h2><div class="info-grid" style="grid-template-columns:1fr">${info('Status',o.status)}${info('Entrada',date(o.entry_date))}${info('Previsão de entrega',date(o.delivery_date))}${info('Garantia até',date(o.warranty_until))}${info('Valor aprovado',money(o.estimated_value))}${info('Pagamento',o.payment_method)}${info('Responsável técnico',o.technician)}${info('Retirado por',o.picked_up_by)}${info('Data da retirada',date(o.pickup_date))}</div></aside></div></div>
    <div class="print-sheet">${printableCopy(o,'VIA DA EMPRESA')}${printableCopy(o,'VIA DO CLIENTE')}</div>`;
  views.detail.querySelector('[data-back]').onclick = () => show('list');
  views.detail.querySelector('#editDetail').onclick = () => editOrder(id);
  views.detail.querySelector('#storePdf').onclick = () => HOSTED_MODE ? downloadPdf(o, 'store') : window.open(o.store_pdf_url, '_blank');
  views.detail.querySelector('#techPdf').onclick = () => HOSTED_MODE ? downloadPdf(o, 'technician') : window.open(o.technician_pdf_url, '_blank');
  views.detail.querySelector('#clientDigital').onclick = () => shareClientPdf(o);
  views.detail.querySelector('#printDetail').onclick = () => window.print();
  show('detail');
}

function printableCopy(o, copyLabel) {
  const line = (label, value) => `<div class="p-field"><b>${label}</b><span>${esc(value || '—')}</span></div>`;
  return `<section class="print-copy">
    <header class="p-head"><div class="p-brand"><img src="/01.jpg" alt="Buzz Tech"><div><strong>BUZZ TECH</strong><small>Assistência técnica especializada</small></div></div><div class="p-number"><small>${esc(o.service_kind || 'ORDEM DE SERVIÇO')} · ${copyLabel}</small><b>${o.number}</b></div></header>
    <div class="p-strip"><b>Entrada:</b> ${date(o.entry_date)} <b>Entrega:</b> ${date(o.delivery_date)} <b>Garantia:</b> ${date(o.warranty_until)} <b>Status:</b> ${esc(o.status)}</div>
    <h3>1. DADOS DO CLIENTE</h3><div class="p-grid p4">${line('Nome completo',o.customer_name)}${line('CPF',o.cpf)}${line('Telefone',o.phone)}${line('E-mail',o.email)}</div>${line('Endereço',o.address)}
    <h3>2. DADOS DO APARELHO</h3><div class="p-grid p5">${line('Aparelho',o.device_type)}${line('Marca',o.brand)}${line('Modelo',o.model)}${line('Cor',o.color)}${line('Capacidade',o.capacity)}</div><div class="p-grid p3">${line('IMEI / Série',o.serial_number)}${line('Senha / padrão',o.unlock_password)}${line('Conta removida',o.account_removed)}</div>
    <div class="p-grid p3 blocks"><div><h3>3. DEFEITO INFORMADO</h3><p>${esc(o.reported_issue)}</p></div><div><h3>4. ESTADO NA ENTRADA</h3><p>${marked(o.device_condition)}</p></div><div><h3>5. ACESSÓRIOS</h3><p>${marked(o.accessories)}</p></div></div>
    <h3>6. CHECKLIST TÉCNICO</h3><p class="p-check">${marked(o.technical_checklist)}</p>
    <div class="p-grid p2 notes"><div><b>Laudo / observações técnicas:</b><p>${esc(o.technical_report || o.notes || '—')}</p></div><div><b>Valor aprovado:</b> ${money(o.estimated_value)}<br><b>Pagamento:</b> ${esc(o.payment_method || '—')}</div></div>
    <div class="p-warranty"><b>GARANTIA REFERENTE A:</b> ${marked(o.warranty_items)}</div>
    <div class="p-warning">TELA TRINCADA, OXIDAÇÃO E DANOS FÍSICOS NÃO SÃO COBERTOS PELA GARANTIA.</div>
    <div class="p-legal">${LEGAL_TERMS.map((term,index)=>`<p><b>${index+1}.</b> ${esc(term)}</p>`).join('')}</div>
    <p class="p-declaration"><b>DECLARAÇÃO DO CLIENTE:</b> ${esc(CLIENT_DECLARATION)}</p>
    <div class="p-grid p4 signatures">${line('Responsável técnico',o.technician)}${line('Recebido por',o.received_by)}${line('Retirado por / CPF',[o.picked_up_by,o.pickup_cpf].filter(Boolean).join(' · '))}${line('Assinatura do cliente','')}</div>
    <footer class="p-footer">Feira dos Importados de Brasília · Bloco A · Loja 73/74 · (61) 98199-4436 · @buzztechbsb · Terça a domingo, 09h às 18h · Este documento não possui valor fiscal.</footer>
  </section>`;
}

form.onsubmit = async event => {
  event.preventDefault();
  const button = document.querySelector('#saveButton');
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Gerando ordem...';
  try {
    const id = document.querySelector('#orderId').value;
    const data = new FormData(form);
    const payload = Object.fromEntries(data.entries());
    delete payload.order_id;
    payload.estimated_value = currencyToNumber(payload.estimated_value);
    ['device_condition','accessories','technical_checklist','warranty_items'].forEach(name => payload[name] = data.getAll(name).join(', '));
    let result;
    if (HOSTED_MODE) {
      const now = new Date().toISOString();
      if (id) {
        const current = orders.find(item => item.id === Number(id));
        result = {...current, ...payload, id:Number(id), updated_at:now};
        orders = orders.map(item => item.id === Number(id) ? result : item);
      } else {
        const nextId = Number(localStorage.getItem('os-digital-sequence') || '0') + 1;
        localStorage.setItem('os-digital-sequence', String(nextId));
        result = {...payload, id:nextId, number:`OS-${String(nextId).padStart(6,'0')}`, created_at:now, updated_at:now};
        orders.unshift(result);
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(orders));
      renderList();
    } else {
      const response = await fetch(id ? `/api/orders/${id}` : '/api/orders', {method: id ? 'PUT' : 'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      result = await responseJson(response);
      await loadOrders();
    }
    toast(id ? 'Alterações salvas.' : `${result.number} criada com sucesso.`);
    openDetail(result.id);
  } catch (error) {
    const offline = location.protocol === 'file:' || !navigator.onLine;
    toast(offline ? 'Abra o sistema pelo iniciar.ps1. O servidor não está conectado.' : (error.message || 'Erro ao gerar a ordem de serviço.'));
    console.error('[OS Digital] Falha ao salvar:', error);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
};

function toast(message) {
  const node = document.querySelector('#toast');
  node.textContent = message; node.classList.add('show');
  setTimeout(() => node.classList.remove('show'), 3000);
}

function cpfMask(value) {
  return value.replace(/\D/g,'').slice(0,11).replace(/(\d{3})(\d)/,'$1.$2').replace(/(\d{3})(\d)/,'$1.$2').replace(/(\d{3})(\d{1,2})$/,'$1-$2');
}

function currencyMask(value) {
  const cents = Number(value.replace(/\D/g,''));
  return (cents / 100).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
}

function currencyToNumber(value) {
  if (!value) return '';
  return (Number(value.replace(/\D/g,'')) / 100).toFixed(2);
}

form.querySelectorAll('[name="cpf"],[name="pickup_cpf"]').forEach(field => field.addEventListener('input', () => field.value = cpfMask(field.value)));
form.elements.estimated_value.addEventListener('input', event => event.target.value = currencyMask(event.target.value));

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
if (location.protocol === 'file:') {
  toast('Use o iniciar.ps1 para abrir o sistema corretamente.');
} else {
  checkServer();
  loadOrders().catch(error => {
    console.error('[OS Digital] Servidor indisponível:', error);
    toast('Servidor desconectado. Feche e execute iniciar.ps1 novamente.');
  });
}

async function downloadPdf(order, variant = 'physical', share = false) {
  const technician = variant === 'technician';
  const clean = value => String(value || '—').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^\x20-\x7E]/g, '?');
  const escapePdf = value => clean(value).replace(/\\/g,'\\\\').replace(/\(/g,'\\(').replace(/\)/g,'\\)');
  const commands = [];
  const text = (x,y,value,size=8,bold=false) => commands.push(`BT /${bold?'F2':'F1'} ${size} Tf ${x} ${y} Td (${escapePdf(value)}) Tj ET`);
  const wrap = (value, width=78) => {
    const words = clean(value).split(/\s+/); const lines=[]; let line='';
    words.forEach(word => { if ((line+' '+word).trim().length > width) { lines.push(line); line=word; } else line=(line+' '+word).trim(); });
    if (line) lines.push(line); return lines.length ? lines : ['—'];
  };
  const field = (x,y,label,value,width=78,max=2) => { text(x,y,label.toUpperCase(),6,true); wrap(value,width).slice(0,max).forEach((line,i)=>text(x,y-10-i*9,line,7)); };
  const legalColumns = startY => {
    [0,6,12].forEach((start,column) => {
      let legalY=startY; const x=30+column*182;
      LEGAL_TERMS.slice(start,start+6).forEach((term,index) => {
        wrap(`${start+index+1}. ${term}`,72).forEach(line => { text(x,legalY,line,3.6); legalY-=4.2; });
        legalY-=1;
      });
    });
  };
  const copy = (top,label) => {
    commands.push(`0.16 0.48 0.82 rg 24 ${top-45} 547 40 re f`,`0 0 0 rg`);
    text(38,top-22,'OS DIGITAL',17,true); text(390,top-22,`${order.number} · ${label}`,10,true);
    let y=top-65; text(30,y,`Entrada: ${order.entry_date||'—'}   Entrega: ${order.delivery_date||'—'}   Status: ${order.status||'—'}`,7,true); y-=22;
    field(30,y,'Cliente',order.customer_name,44); field(265,y,'Contato',order.phone||order.email,42); y-=32;
    field(30,y,'CPF',order.cpf,24); field(165,y,'Aparelho',[order.device_type,order.brand,order.model].filter(Boolean).join(' · '),45); field(405,y,'Senha',order.unlock_password,24); y-=32;
    field(30,y,'Problema informado',order.reported_issue,70,3); field(330,y,'Estado na entrada',order.device_condition,42,3); y-=45;
    field(30,y,'Diagnostico / laudo',order.technical_report||'A preencher',70,3); field(350,y,'Valor',`R$ ${order.estimated_value||'—'}`,25); y-=45;
    field(30,y,'Acessorios',order.accessories,62,2); field(330,y,'Checklist',order.technical_checklist,48,2); y-=38;
    text(30,y,`GARANTIA REFERENTE A: ${order.warranty_items||'—'}`,4,true); y-=8;
    text(30,y,'TELA TRINCADA, OXIDACAO E DANOS FISICOS NAO SAO COBERTOS PELA GARANTIA.',4,true); y-=8;
    legalColumns(y); wrap(`DECLARACAO: ${CLIENT_DECLARATION}`,165).slice(0,2).forEach((line,index)=>text(30,top-325-index*4,line,3.4));
    text(30,top-345,'Tecnico: ____________________   Cliente: ____________________   Data: ____/____/______',4.5);
    text(30,top-363,'Feira dos Importados de Brasilia · Bloco A · Loja 73/74 · (61) 98199-4436 · @buzztechbsb',3.4);
    text(30,top-373,'Terca a domingo, 09h as 18h (inclusive feriados) · Este documento nao possui valor fiscal.',3.4);
    commands.push(`0.7 0.7 0.7 RG 24 ${top-395} 547 395 re S`);
  };
  if (technician) {
    commands.push('0.16 0.48 0.82 rg','6 213 130 36 re f','0 0 0 rg'); text(12,232,'BUZZ TECH',12,true); text(88,232,order.number,7,true); text(12,219,'FICHA DO TECNICO · 5 x 9 cm',5);
    let y=199; [['Cliente',order.customer_name],['Contato',order.phone||order.email],['Senha / padrao',order.unlock_password],['Problema / diagnostico',order.technical_report||order.reported_issue||'A preencher']].forEach(([label,value],index)=>{field(10,y,label,value,index===3?34:36,index===3?5:3);y-=index===3?0:43;});
    text(10,18,'Tecnico: ____________________',6); text(10,8,'Data: ____/____/______',6);
  } else if (variant === 'client') { copy(420,'VIA DIGITAL DO CLIENTE'); }
  else if (variant === 'store') { copy(420,'VIA ARQUIVADA DA LOJA'); }
  else { copy(830,'VIA DA EMPRESA'); copy(420,'VIA DO CLIENTE'); }
  const stream=commands.join('\n');
  const pageSize = technician ? '0 0 142 255' : variant === 'physical' ? '0 0 595 842' : '0 0 595 421';
  const objects=[`<< /Type /Catalog /Pages 2 0 R >>`,`<< /Type /Pages /Kids [3 0 R] /Count 1 >>`,`<< /Type /Page /Parent 2 0 R /MediaBox [${pageSize}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>`,`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,`<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`,`<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>`];
  let pdf='%PDF-1.4\n'; const offsets=[0]; objects.forEach((obj,i)=>{offsets.push(pdf.length);pdf+=`${i+1} 0 obj\n${obj}\nendobj\n`;}); const xref=pdf.length; pdf+=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`; offsets.slice(1).forEach(offset=>pdf+=`${String(offset).padStart(10,'0')} 00000 n \n`); pdf+=`trailer << /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  const suffix = technician ? '-TECNICO' : variant === 'client' ? '-CLIENTE-DIGITAL' : variant === 'store' ? '-LOJA' : '';
  const blob=new Blob([pdf],{type:'application/pdf'});
  await shareOrDownload(blob, `${order.number}${suffix}.pdf`, share);
}

async function shareOrDownload(blob, filename, share = false) {
  const file = new File([blob], filename, {type:'application/pdf'});
  if (share && navigator.share && navigator.canShare?.({files:[file]})) {
    try { await navigator.share({title:`Buzz Tech · ${filename}`,text:'Sua Ordem de Serviço Buzz Tech',files:[file]}); return; }
    catch (error) { if (error.name === 'AbortError') return; }
  }
  const link=document.createElement('a'); link.href=URL.createObjectURL(blob); link.download=filename; link.click(); setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  if (share) toast('PDF do cliente baixado. Anexe o arquivo na conversa do WhatsApp.');
}

async function shareClientPdf(order) {
  if (HOSTED_MODE) return downloadPdf(order, 'client', true);
  try {
    const response = await fetch(order.client_pdf_url);
    if (!response.ok) throw new Error('Não foi possível gerar a via digital.');
    await shareOrDownload(await response.blob(), `${order.number}-CLIENTE-DIGITAL.pdf`, true);
  } catch (error) { toast(error.message); }
}
