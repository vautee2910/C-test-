const header = document.querySelector('.topbar');
const sections = [...document.querySelectorAll('main section[id]')];
const navLinks = [...document.querySelectorAll('.topbar nav a')];

window.addEventListener('scroll', () => {
  header.classList.toggle('scrolled', window.scrollY > 20);
  const current = sections.filter(section => section.offsetTop <= window.scrollY + 180).at(-1);
  navLinks.forEach(link => link.toggleAttribute('aria-current', current && link.hash === `#${current.id}`));
}, { passive: true });

const observer = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) entry.target.classList.add('visible');
  });
}, { threshold: .12 });

document.querySelectorAll('.pipeline-card, .principle-grid article, .stack-grid article, .roadmap-grid article').forEach(el => observer.observe(el));
