/* Tactus Angelis by Mirjam — interactie */
(() => {
  'use strict';

  const OPSLAG_SLEUTEL = 'tactus_reviews';

  /* ── Mobiel menu ──────────────────────────────────────────── */
  const toggle = document.getElementById('nav-toggle');
  const navLinks = document.getElementById('nav-links');

  if (toggle && navLinks) {
    const zetMenu = (open) => {
      navLinks.classList.toggle('open', open);
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Menu sluiten' : 'Menu openen');
    };

    toggle.addEventListener('click', () => {
      zetMenu(toggle.getAttribute('aria-expanded') !== 'true');
    });
    navLinks.addEventListener('click', (e) => {
      if (e.target.closest('a')) zetMenu(false);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') zetMenu(false);
    });
  }

  /* ── Sitenaam in de nav verschijnt na de header ────────────── */
  const sitenaam = document.getElementById('nav-sitenaam');
  const header = document.querySelector('.tactus-header');

  if (sitenaam && header && 'IntersectionObserver' in window) {
    new IntersectionObserver(
      ([entry]) => sitenaam.classList.toggle('zichtbaar', !entry.isIntersecting),
      { rootMargin: '-80px 0px 0px 0px' }
    ).observe(header);
  }

  /* ── Elementen laten verschijnen bij scrollen ──────────────── */
  const teOnthullen = document.querySelectorAll('.reveal');

  if ('IntersectionObserver' in window) {
    const waarnemer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('in-beeld');
        waarnemer.unobserve(entry.target);
      });
    }, { threshold: 0.15 });
    teOnthullen.forEach((el) => waarnemer.observe(el));
  } else {
    teOnthullen.forEach((el) => el.classList.add('in-beeld'));
  }

  /* ── Jaartal in de footer ──────────────────────────────────── */
  const jaartal = document.getElementById('jaartal');
  if (jaartal) jaartal.textContent = String(new Date().getFullYear());

  /* ── Reviews ───────────────────────────────────────────────── */
  const form = document.getElementById('review-form');
  const lijst = document.getElementById('reviews-lijst');
  const melding = document.getElementById('review-melding');
  const sterrenVeld = document.getElementById('sterren');

  // localStorage kan geblokkeerd zijn (privémodus); dan werkt de rest gewoon door.
  const leesReviews = () => {
    try {
      const ruw = JSON.parse(localStorage.getItem(OPSLAG_SLEUTEL) || '[]');
      return Array.isArray(ruw) ? ruw : [];
    } catch {
      return [];
    }
  };

  const bewaarReviews = (reviews) => {
    try {
      localStorage.setItem(OPSLAG_SLEUTEL, JSON.stringify(reviews));
      return true;
    } catch {
      return false;
    }
  };

  const kleurSterren = (aantal) => {
    if (!sterrenVeld) return;
    sterrenVeld.querySelectorAll('label').forEach((label, i) => {
      const gevuld = i < aantal;
      label.classList.toggle('actief', gevuld);
      label.querySelector('[aria-hidden]').textContent = gevuld ? '★' : '☆';
    });
  };

  const gekozenSterren = () => {
    const gekozen = sterrenVeld && sterrenVeld.querySelector('input:checked');
    return gekozen ? Number(gekozen.value) : 0;
  };

  if (sterrenVeld) {
    sterrenVeld.addEventListener('change', () => kleurSterren(gekozenSterren()));
    sterrenVeld.querySelectorAll('label').forEach((label, i) => {
      label.addEventListener('mouseenter', () => kleurSterren(i + 1));
    });
    sterrenVeld.addEventListener('mouseleave', () => kleurSterren(gekozenSterren()));
  }

  const toonReviews = () => {
    if (!lijst) return;
    const reviews = leesReviews();
    lijst.textContent = '';

    if (reviews.length === 0) {
      const leeg = document.createElement('li');
      leeg.className = 'reviews-leeg';
      leeg.textContent = 'Nog geen reviews — wees de eerste! 🌟';
      lijst.append(leeg);
      return;
    }

    reviews.forEach((r) => {
      const aantal = Math.min(5, Math.max(1, Number(r.sterren) || 5));
      const kaart = document.createElement('li');
      kaart.className = 'review-card';

      const sterren = document.createElement('p');
      sterren.className = 'review-sterren';
      sterren.textContent = '★'.repeat(aantal) + '☆'.repeat(5 - aantal);

      const tekst = document.createElement('p');
      tekst.className = 'review-tekst';
      tekst.textContent = `“${r.tekst}”`;

      const auteur = document.createElement('p');
      auteur.className = 'review-auteur';
      auteur.textContent = `— ${r.naam}${r.datum ? ` · ${r.datum}` : ''}`;

      kaart.append(sterren, tekst, auteur);
      lijst.append(kaart);
    });
  };

  const meldingTonen = (tekst, soort) => {
    if (!melding) return;
    melding.className = `review-melding ${soort}`;
    melding.textContent = tekst;
  };

  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();

      const naamVeld = document.getElementById('review-naam');
      const tekstVeld = document.getElementById('review-tekst');
      const naam = naamVeld.value.trim();
      const tekst = tekstVeld.value.trim();
      const sterren = gekozenSterren();

      if (!naam) { meldingTonen('Vul je naam in.', 'fout'); naamVeld.focus(); return; }
      if (!tekst) { meldingTonen('Schrijf je ervaring.', 'fout'); tekstVeld.focus(); return; }
      if (sterren === 0) { meldingTonen('Kies een aantal sterren.', 'fout'); return; }

      const reviews = leesReviews();
      reviews.unshift({
        naam, tekst, sterren,
        datum: new Date().toLocaleDateString('nl-NL')
      });

      if (!bewaarReviews(reviews)) {
        meldingTonen('Je review kon niet bewaard worden in deze browser.', 'fout');
        return;
      }

      form.reset();
      kleurSterren(0);
      toonReviews();
      meldingTonen('✦ Dankjewel voor je review!', 'gelukt');
      setTimeout(() => meldingTonen('', ''), 4000);
    });
  }

  kleurSterren(0);
  toonReviews();
})();
