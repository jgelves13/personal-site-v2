// ===== NAV BORDER ON SCROLL =====
const header = document.querySelector('header');
window.addEventListener('scroll', () => {
  header.classList.toggle('bordered', window.scrollY > 10);
}, { passive: true });

// ===== HAMBURGER =====
const hamburger = document.getElementById('hamburger');
const mobileNav  = document.getElementById('mobileNav');

hamburger.addEventListener('click', () => {
  const open = mobileNav.classList.toggle('open');
  const [a, b, c] = hamburger.querySelectorAll('span');
  if (open) {
    a.style.transform = 'translateY(7px) rotate(45deg)';
    b.style.opacity   = '0';
    c.style.transform = 'translateY(-7px) rotate(-45deg)';
  } else {
    a.style.transform = b.style.opacity = c.style.transform = '';
  }
});
mobileNav.querySelectorAll('a').forEach(l => l.addEventListener('click', () => {
  mobileNav.classList.remove('open');
  const [a, b, c] = hamburger.querySelectorAll('span');
  a.style.transform = b.style.opacity = c.style.transform = '';
}));

// ===== LANGUAGE TOGGLE =====
let lang = 'en';


function applyLang(l) {
  lang = l;
  document.documentElement.lang = l;
  document.querySelectorAll('[id^="langToggle"]').forEach(btn => {
    btn.textContent = l === 'en' ? 'EN | ES' : 'ES | EN';
  });
  document.querySelectorAll('[data-en]').forEach(el => {
    const val = l === 'en' ? el.dataset.en : el.dataset.es;
    if (!val) return;
    if (val.includes('<') || val.includes('&')) el.innerHTML = val;
    else el.textContent = val;
  });
  // swap CV download links
  document.querySelectorAll('[data-cv-en]').forEach(el => {
    el.setAttribute('href', l === 'en' ? el.dataset.cvEn : el.dataset.cvEs);
  });
}

document.getElementById('langToggle').addEventListener('click', () => applyLang(lang === 'en' ? 'es' : 'en'));
document.getElementById('langToggleMob').addEventListener('click', () => applyLang(lang === 'en' ? 'es' : 'en'));

// ===== SCROLL REVEAL =====
const observer = new IntersectionObserver((entries) => {
  entries.forEach((entry) => {
    if (!entry.isIntersecting) return;
    // When any item fires, reveal it and all remaining siblings with stagger
    const siblings = Array.from(entry.target.parentElement.querySelectorAll('.reveal:not(.in-view)'));
    siblings.forEach((el, idx) => {
      setTimeout(() => el.classList.add('in-view'), idx * 60);
      observer.unobserve(el);
    });
  });
}, { threshold: 0.01, rootMargin: '0px 0px 120px 0px' });

document.querySelectorAll('.reveal').forEach(el => observer.observe(el));

// ===== SMOOTH SCROLL =====
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const t = document.querySelector(a.getAttribute('href'));
    if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  });
});
