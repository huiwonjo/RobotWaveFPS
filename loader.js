document.documentElement.lang = 'ko';
const loading = document.getElementById('boot-loading');
loading.append(document.getElementById('transfer'), document.getElementById('infobox'));
const start = document.getElementById('boot-start');
let ready = false;
window.gameAwaitGesture = () => {
  start.disabled = false;
  start.textContent = '서울의 밤에 입장하기  →';
  document.getElementById('status').textContent = '연결 완료 / 출동 준비';
};
window.gameReady = () => {
  ready = true;
  document.getElementById('boot-screen').hidden = true;
  document.getElementById('canvas').focus();
};
start.addEventListener('click', () => {
  if (start.dataset.retry) { location.reload(); return; }
  start.textContent = '야간 순찰을 준비하는 중…';
  document.getElementById('canvas').focus();
});
window.addEventListener('error', event => {
  if (ready || !event.message) return;
  document.getElementById('infobox').textContent = '게임을 불러오지 못했습니다. 연결을 확인한 뒤 다시 시도하세요.';
  start.textContent = '다시 불러오기';
  start.dataset.retry = 'true';
  start.disabled = false;
});
if (location.protocol === 'file:') {
  document.getElementById('infobox').textContent = '웹 버전은 로컬 서버에서 실행하세요. PC에서는 게임실행.bat으로 바로 시작할 수 있습니다.';
}
