/**
 * AI 문해력 논술 코칭 - 학생 화면 로직
 *
 * - 책 목록(제목+질문)은 서버(/api/books)에서 받아옵니다.
 * - 글은 /submit 으로 보내고, 서버가 돌려준 "내 글의 결과"만 이 탭(sessionStorage)에 보관합니다.
 * - 별명, 연속 일수, 쓴 글 수는 이 기기(localStorage)에만 저장하고 서버로 보내지 않습니다.
 * - API_BASE는 index.html의 인라인 스크립트에서 window.API_BASE로 주입됩니다.
 */

// ---------------------------------------------------------------
// 저장소 도우미 (사생활 보호 모드 등에서 저장이 막혀도 앱이 멈추지 않게)
// ---------------------------------------------------------------
function lsGet(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (e) { return null; } }
function lsSet(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 무시 */ } }
function lsDel(key) { try { localStorage.removeItem(key); } catch (e) { /* 무시 */ } }
function ssGet(key) { try { return JSON.parse(sessionStorage.getItem(key)); } catch (e) { return null; } }
function ssSet(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 무시 */ } }

const KEY_NICK = 'lc_nick';
const KEY_STATS = 'lc_stats';
const KEY_RESULTS = 'myEssayResults';

// ---------------------------------------------------------------
// 화면 구성 데이터
// ---------------------------------------------------------------
const ADJECTIVES = ['용감한', '호기심 많은', '차분한', '씩씩한', '따뜻한', '반짝이는'];
const ANIMALS = ['호랑이', '여우', '고래', '부엉이', '거북이', '다람쥐'];
const ANIMAL_COLORS = { '호랑이': '#F6C877', '여우': '#FFB596', '고래': '#B9BCF8', '부엉이': '#A5E0C5', '거북이': '#8FD3B6', '다람쥐': '#F3D9A4' };
const DEFAULT_NAME = '글쓰기 친구';

const CHAPTERS = {
    1: { name: '세상의 시작', icon: 'i-sunrise', cls: 'k1', color: '#FF8B5E' },
    2: { name: '영웅 이야기', icon: 'i-bolt', cls: 'k2', color: '#8E92F2' },
    3: { name: '사랑과 가족', icon: 'i-heart', cls: 'k3', color: '#67C9A0' },
    4: { name: '웃음 속 풍자', icon: 'i-smile', cls: 'k4', color: '#0C5846' },
    5: { name: '동물과 사물', icon: 'i-leaf', cls: 'k5', color: '#E0A93F' },
};

const LEVELS = [
    { min: 0, title: '이야기 새싹', lv: 1 },
    { min: 3, title: '이야기 탐험가', lv: 2 },
    { min: 10, title: '생각 모험가', lv: 3 },
    { min: 25, title: '글쓰기 달인', lv: 4 },
];

const state = {
    books: [],
    byId: {},
    chapterNo: null,
    currentBook: null,
    prevView: 'v-home',
    nickDraft: { adj: ADJECTIVES[0], ani: ANIMALS[0] },
    nickCancelable: false,
};

// ---------------------------------------------------------------
// 공통 유틸
// ---------------------------------------------------------------
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
}

function icon(id, cls) {
    return `<svg class="${cls || 'ico'}" viewBox="0 0 24 24"><use href="#${id}"/></svg>`;
}

function chapterNo(book) {
    const n = parseInt(book.chapter, 10);
    return CHAPTERS[n] ? n : 1;
}

function mascot(size, face) {
    const eye = '#0C5846';
    return `<svg width="${size}" height="${size}" viewBox="0 0 30 30" aria-hidden="true">
        <circle cx="15" cy="15" r="11" fill="#fff"/>
        <circle cx="11.2" cy="13.5" r="1.6" fill="${eye}"/><circle cx="18.8" cy="13.5" r="1.6" fill="${eye}"/>
        <path d="M10.5 18c1.3 2 2.6 2.8 4.5 2.8s3.2-.8 4.5-2.8" fill="none" stroke="${eye}" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M15 3.5c1.6 1.6 2.2 3 2 4.4-1.7-.4-2.7-1.4-2-4.4z" fill="#67C9A0"/>
    </svg>`;
}

function todayStr() {
    const d = new Date();
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function dayDiff(a, b) {
    return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000);
}

// ---------------------------------------------------------------
// 별명 / 기록 (이 기기에만 저장)
// ---------------------------------------------------------------
function getNick() {
    const n = lsGet(KEY_NICK);
    if (!n || typeof n !== 'object') return null;
    if (n.skip) return { name: DEFAULT_NAME, adj: null, animal: null, skip: true };
    if (ADJECTIVES.includes(n.adj) && ANIMALS.includes(n.ani)) return { name: n.adj + ' ' + n.ani, adj: n.adj, animal: n.ani, skip: false };
    return null;
}

function getStats() {
    const s = lsGet(KEY_STATS) || {};
    const count = Number.isFinite(s.count) ? s.count : 0;
    const last = typeof s.last === 'string' ? s.last : '';
    let streak = Number.isFinite(s.streak) ? s.streak : 0;
    // 어제 또는 오늘 쓴 경우에만 연속으로 인정
    if (!last || dayDiff(last, todayStr()) > 1) streak = 0;
    return { count, last, streak };
}

function levelOf(count) {
    let cur = LEVELS[0];
    LEVELS.forEach(l => { if (count >= l.min) cur = l; });
    return cur;
}

function recordWritten() {
    const raw = lsGet(KEY_STATS) || {};
    const today = todayStr();
    const count = (Number.isFinite(raw.count) ? raw.count : 0) + 1;
    let streak = Number.isFinite(raw.streak) ? raw.streak : 0;
    if (raw.last === today) {
        streak = Math.max(streak, 1);
    } else if (raw.last && dayDiff(raw.last, today) === 1) {
        streak += 1;
    } else {
        streak = 1;
    }
    lsSet(KEY_STATS, { count, last: today, streak });
    return { count, streak };
}

function renderProfile() {
    const nick = getNick();
    const stats = getStats();
    const lv = levelOf(stats.count);
    const name = nick ? nick.name : DEFAULT_NAME;
    const bg = nick && nick.animal ? ANIMAL_COLORS[nick.animal] : '#F6C877';

    const avatarSet = (id, size) => {
        const el = document.getElementById(id);
        if (el) { el.style.background = bg; el.innerHTML = mascot(size); }
    };
    avatarSet('heroAvatar', 30);
    avatarSet('meAvatar', 52);

    document.getElementById('heroName').textContent = name;
    document.getElementById('heroTitle').textContent = lv.title + ' · Lv.' + lv.lv;
    document.getElementById('meName').textContent = name;
    document.getElementById('meTitle').textContent = lv.title + ' · Lv.' + lv.lv;
    document.getElementById('meStreak').textContent = stats.streak;
    document.getElementById('meCount').textContent = stats.count;

    const badges = [];
    if (stats.streak >= 1) badges.push(`<span class="badge">${icon('i-flame', '')}${stats.streak}일 연속</span>`);
    if (stats.count >= 1) badges.push(`<span class="badge">${icon('i-medal', '')}글 ${stats.count}편</span>`);
    if (!badges.length) badges.push(`<span class="badge">${icon('i-sparkle', '')}첫 글을 기다려요</span>`);
    document.getElementById('heroBadges').innerHTML = badges.join('');
}

// ----- 별명 정하기 화면 -----
function renderNickPicker() {
    const mk = (list, key) => list.map(v =>
        `<button class="opt${state.nickDraft[key] === v ? ' on' : ''}" data-key="${key}" data-val="${escapeHtml(v)}">${escapeHtml(v)}</button>`
    ).join('');
    document.getElementById('adjOpts').innerHTML = mk(ADJECTIVES, 'adj');
    document.getElementById('aniOpts').innerHTML = mk(ANIMALS, 'ani');
    document.getElementById('nickPreview').textContent = state.nickDraft.adj + ' ' + state.nickDraft.ani;
    const av = document.getElementById('nickAvatar');
    av.style.background = ANIMAL_COLORS[state.nickDraft.ani];
    av.innerHTML = mascot(52);
    document.querySelectorAll('#nickOverlay .opt').forEach(btn => {
        btn.onclick = () => {
            state.nickDraft[btn.dataset.key] = btn.dataset.val;
            renderNickPicker();
        };
    });
}

function openNick(cancelable) {
    state.nickCancelable = !!cancelable;
    const cur = getNick();
    if (cur && !cur.skip) state.nickDraft = { adj: cur.adj, ani: cur.animal };
    document.getElementById('skipBtn').textContent = cancelable ? '닫기' : '나중에 할게요';
    renderNickPicker();
    document.getElementById('nickOverlay').classList.add('show');
}

function closeNick() { document.getElementById('nickOverlay').classList.remove('show'); }

function saveNick() {
    lsSet(KEY_NICK, { adj: state.nickDraft.adj, ani: state.nickDraft.ani });
    closeNick();
    renderProfile();
}

function skipNick() {
    if (!state.nickCancelable) lsSet(KEY_NICK, { skip: true });
    closeNick();
    renderProfile();
}

function resetNick() {
    if (!confirm('이 기기에 저장된 별명과 기록을 지우고 새로 시작할까요?')) return;
    lsDel(KEY_NICK);
    lsDel(KEY_STATS);
    try { sessionStorage.removeItem(KEY_RESULTS); } catch (e) { /* 무시 */ }
    renderProfile();
    loadReports();
    show('v-home');
    openNick(false);
}

// ---------------------------------------------------------------
// 화면 전환
// ---------------------------------------------------------------
function show(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === viewId));
    const tabbar = document.getElementById('tabbar');
    const hideTab = ['v-books', 'v-write', 'v-result'].includes(viewId);
    tabbar.classList.toggle('hidden', hideTab);
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('on', t.dataset.view === viewId));
    if (viewId === 'v-reports') loadReports();
    if (viewId === 'v-me' || viewId === 'v-home') renderProfile();
    window.scrollTo(0, 0);
}

// ---------------------------------------------------------------
// 책 고르기
// ---------------------------------------------------------------
async function loadBooks() {
    const grid = document.getElementById('chapterGrid');
    try {
        const response = await fetch(`${window.API_BASE}/api/books`);
        if (!response.ok) throw new Error('책 목록을 불러오지 못했습니다.');
        const data = await response.json();
        state.books = data.books || [];
        state.byId = {};
        state.books.forEach(b => { state.byId[b.id] = b; });

        const counts = {};
        state.books.forEach(b => { const n = chapterNo(b); counts[n] = (counts[n] || 0) + 1; });
        const html = Object.keys(CHAPTERS).filter(n => counts[n]).map(n => {
            const ch = CHAPTERS[n];
            return `<button class="chip ${ch.cls}" onclick="openChapter(${n})">
                <svg class="i" viewBox="0 0 24 24"><use href="#${ch.icon}"/></svg>${escapeHtml(ch.name)}<small>${counts[n]}권</small></button>`;
        }).join('');
        grid.innerHTML = html + '<div class="chip k6">더 많은 이야기가<br>곧 열려요</div>';
    } catch (e) {
        grid.innerHTML = '<div class="empty" style="grid-column:1/-1;padding:30px 0;">책 목록을 불러오지 못했어요.<br>새로고침 해 주세요.</div>';
    }
}

function openChapter(n) {
    state.chapterNo = n;
    const ch = CHAPTERS[n];
    document.getElementById('chapterTitle').textContent = ch.name;
    document.getElementById('bookList').innerHTML = state.books.filter(b => chapterNo(b) === n).map(b =>
        `<button class="bookrow" onclick="openBook(${b.id})">
            <div class="no" style="background:${ch.color}">${b.id}</div>
            <div><b>${escapeHtml(b.title)}</b><span>${escapeHtml(b.question)}</span></div>
        </button>`).join('');
    show('v-books');
}

function openBook(id) {
    const book = state.byId[id];
    if (!book) return;
    state.currentBook = book;
    document.getElementById('writeTitle').textContent = book.title;
    document.getElementById('questionText').textContent = book.question;
    document.getElementById('textInput').value = '';
    document.getElementById('result').textContent = '';
    updateCount();
    show('v-write');
}

function backFromWrite() { show(state.chapterNo ? 'v-books' : 'v-home'); }

function updateCount() {
    const len = document.getElementById('textInput').value.length;
    document.getElementById('countText').textContent = len + ' / 1500';
}

// ---------------------------------------------------------------
// 제출
// ---------------------------------------------------------------
async function submitEssay(event) {
    const textInput = document.getElementById('textInput');
    const resultDiv = document.getElementById('result');
    const button = document.getElementById('submitBtn');
    const text = textInput.value.trim();
    const book = state.currentBook;

    resultDiv.style.color = '#D4502B';
    if (!book) { resultDiv.textContent = '읽은 책을 먼저 골라 주세요.'; return; }
    if (text.length < 10) { resultDiv.textContent = '글이 너무 짧아요. 10자 이상 써 주세요.'; return; }

    button.disabled = true;
    button.textContent = 'AI 선생님이 읽고 있어요...';
    resultDiv.style.color = '#5D6B64';
    resultDiv.textContent = '잠시만 기다려 주세요. 보통 10초쯤 걸려요.';

    try {
        const response = await fetch(`${window.API_BASE}/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, book_id: Number(book.id) })
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || '제출 중 오류가 발생했습니다.');

        const result = payload.result;
        if (result) {
            const mine = ssGet(KEY_RESULTS) || [];
            mine.unshift(result);
            ssSet(KEY_RESULTS, mine.slice(0, 20));
        }
        const progress = recordWritten();
        textInput.value = '';
        resultDiv.textContent = '';
        renderProfile();
        state.prevView = 'v-home';
        renderResult(result, progress);
        show('v-result');
    } catch (error) {
        resultDiv.style.color = '#D4502B';
        resultDiv.textContent = error.message;
    } finally {
        button.disabled = false;
        button.textContent = '제출하기';
    }
}

// ---------------------------------------------------------------
// 결과 / 리포트
// ---------------------------------------------------------------
function fbCard(cls, iconId, title, text) {
    if (!text) return '';
    return `<div class="fb ${cls}"><h4>${icon(iconId, '')}${escapeHtml(title)}</h4>${escapeHtml(text)}</div>`;
}

function renderResult(essay, progress) {
    const body = document.getElementById('resultBody');
    if (!essay) { body.innerHTML = '<div class="empty">결과를 불러올 수 없어요.</div>'; return; }
    const d = (essay.evaluation && essay.evaluation.dimensions) || {};
    const val = k => (d[k] && d[k].value) || 0;
    const fb = (essay.ai_feedback && essay.ai_feedback.feedback_sections) || {};
    const hasSections = fb.praise || fb.improve || fb.question;
    const bookTitle = essay.lesson_context && essay.lesson_context.book_title;
    document.getElementById('resultTitle').textContent = bookTitle ? bookTitle : '내 글 리포트';

    let html = '';
    if (progress) {
        const lv = levelOf(progress.count);
        html += `<div class="banner">${icon('i-flame', '')}오늘도 글을 썼어요! ${progress.streak}일 연속 · ${escapeHtml(lv.title)} Lv.${lv.lv}</div>`;
    }
    html += `<div class="score">
        <div class="sc" style="background:#FF8B5E"><b>${val('vocabulary')}</b><small>어휘</small></div>
        <div class="sc" style="background:#8E92F2"><b>${val('grammar')}</b><small>문법</small></div>
        <div class="sc" style="background:#0C5846"><b>${val('logic')}</b><small>논리</small></div>
        <div class="sc" style="background:#67C9A0;color:#06382b"><b>${val('empathy')}</b><small>공감</small></div>
    </div>`;
    if (hasSections) {
        html += fbCard('g', 'i-star', '잘한 점', fb.praise);
        html += fbCard('o', 'i-pen', '이렇게 고쳐 보면 좋아요', fb.improve);
        html += fbCard('p', 'i-bulb', '생각을 넓히는 질문', fb.question);
    } else {
        html += fbCard('g', 'i-star', 'AI 선생님의 피드백', essay.ai_feedback && essay.ai_feedback.ai_draft_feedback);
    }
    html += fbCard('o', 'i-lock', '개인정보 알림', essay.ai_feedback && essay.ai_feedback.privacy_note);
    html += fbCard('n', 'i-sparkle', 'AI가 다듬은 문장', essay.ai_feedback && essay.ai_feedback.revised_text);
    html += fbCard('n', 'i-doc', '내가 쓴 글', essay.student_essay && essay.student_essay.student_answer);
    html += `<button class="btn" onclick="show('v-home')">다른 책 쓰기</button>`;
    body.innerHTML = html;
}

function backFromResult() { show(state.prevView || 'v-home'); }

function loadReports() {
    const list = document.getElementById('reportsList');
    const items = ssGet(KEY_RESULTS) || [];
    window.reportsData = items;
    if (!items.length) {
        list.innerHTML = `<div class="empty">${icon('i-mail', 'ico').replace('class="ico"', 'class="ico" style="width:42px;height:42px;stroke:#B7C4BD"')}
            아직 제출한 글이 없어요.<br>글을 쓰고 제출하면 여기에 피드백이 모여요.</div>`;
        return;
    }
    list.innerHTML = items.map((essay, i) => {
        const d = (essay.evaluation && essay.evaluation.dimensions) || {};
        const v = k => (d[k] && d[k].value) || 0;
        const when = essay.student_essay && essay.student_essay.submitted_at ? new Date(essay.student_essay.submitted_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
        const title = (essay.lesson_context && essay.lesson_context.book_title) || '내 글';
        const answer = (essay.student_essay && essay.student_essay.student_answer) || '';
        return `<button class="rcard" onclick="openReport(${i})">
            <div class="meta"><span>${escapeHtml(when)}</span></div>
            <b>${escapeHtml(title)}</b>
            <div class="pv">${escapeHtml(answer)}</div>
            <div class="dots"><i>어휘 ${v('vocabulary')}</i><i>문법 ${v('grammar')}</i><i>논리 ${v('logic')}</i><i>공감 ${v('empathy')}</i></div>
        </button>`;
    }).join('');
}

function openReport(i) {
    const essay = (window.reportsData || [])[i];
    if (!essay) return;
    state.prevView = 'v-reports';
    renderResult(essay, null);
    show('v-result');
}

// ---------------------------------------------------------------
// 시작
// ---------------------------------------------------------------
window.addEventListener('DOMContentLoaded', () => {
    renderProfile();
    loadBooks();
    if (!getNick()) openNick(false);
});
