import json
from datetime import datetime
from pathlib import Path

from jinja2 import Template

from config import GALLERIES_DIR


TEMPLATE = Template("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }} - Art Reference Gallery</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0a0a0a; color: #e0e0e0; }

.header {
  position: sticky; top: 0; z-index: 100;
  background: rgba(10,10,10,0.95); backdrop-filter: blur(12px);
  padding: 16px 24px; border-bottom: 1px solid #222;
}
.header h1 { font-size: 24px; font-weight: 600; color: #fff; }
.header .meta { font-size: 13px; color: #888; margin-top: 4px; }

.filters {
  display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; align-items: center;
}
.filters label { font-size: 13px; color: #999; margin-right: 4px; }
.tag-btn {
  padding: 4px 12px; border-radius: 16px; border: 1px solid #333;
  background: transparent; color: #aaa; cursor: pointer; font-size: 12px;
  transition: all 0.2s;
}
.tag-btn:hover, .tag-btn.active { background: #e94560; color: #fff; border-color: #e94560; }
.score-filter { display: flex; align-items: center; gap: 6px; }
.score-filter input[type=range] {
  width: 120px; accent-color: #e94560;
}
.score-filter span { font-size: 12px; color: #999; min-width: 30px; }

.masonry {
  column-count: 4; column-gap: 12px; padding: 20px 24px;
}
@media (max-width: 1200px) { .masonry { column-count: 3; } }
@media (max-width: 800px) { .masonry { column-count: 2; } }
@media (max-width: 500px) { .masonry { column-count: 1; } }

.card {
  break-inside: avoid; margin-bottom: 12px; border-radius: 12px;
  overflow: hidden; background: #161616; cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s; position: relative;
}
.card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(233,69,96,0.15); }
.card img {
  width: 100%; display: block; object-fit: cover;
}
.card-overlay {
  position: absolute; bottom: 0; left: 0; right: 0;
  padding: 16px 12px 12px;
  background: linear-gradient(transparent, rgba(0,0,0,0.85));
  opacity: 0; transition: opacity 0.2s;
}
.card:hover .card-overlay { opacity: 1; }
.card-overlay .desc { font-size: 12px; color: #ccc; margin-bottom: 6px; line-height: 1.4; }
.card-overlay .tags { display: flex; flex-wrap: wrap; gap: 4px; }
.card-overlay .tag {
  font-size: 10px; padding: 2px 6px; border-radius: 8px;
  background: rgba(233,69,96,0.3); color: #f0a0b0;
}
.score-badge {
  position: absolute; top: 8px; right: 8px;
  background: rgba(0,0,0,0.7); color: #e94560; font-size: 13px; font-weight: 700;
  padding: 2px 8px; border-radius: 8px;
}

.modal {
  display: none; position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.92); justify-content: center; align-items: center;
}
.modal.active { display: flex; }
.modal img { max-width: 90vw; max-height: 90vh; object-fit: contain; border-radius: 8px; }
.modal-info {
  position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: rgba(22,22,22,0.95); padding: 16px 24px; border-radius: 12px;
  max-width: 600px; text-align: center;
}
.modal-info .tags { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; justify-content: center; }
.modal-info .tag { font-size: 11px; padding: 3px 8px; border-radius: 10px; background: rgba(233,69,96,0.3); color: #f0a0b0; }
.modal-close {
  position: absolute; top: 20px; right: 24px; font-size: 28px;
  color: #888; cursor: pointer; background: none; border: none;
}
.modal-close:hover { color: #fff; }

.no-results {
  text-align: center; padding: 80px 20px; color: #666; font-size: 16px;
}
</style>
</head>
<body>
<div class="header">
  <h1>{{ title }}</h1>
  <div class="meta">{{ image_count }} images &middot; {{ created_at }}</div>
  <div class="filters">
    <label>Tags:</label>
    {% for tag in all_tags %}
    <button class="tag-btn" data-tag="{{ tag }}">{{ tag }}</button>
    {% endfor %}
    <div class="score-filter">
      <label>Score &ge;</label>
      <input type="range" id="scoreRange" min="0" max="10" step="0.5" value="0">
      <span id="scoreVal">0</span>
    </div>
  </div>
</div>

<div class="masonry" id="gallery">
{% for img in images %}
<div class="card"
     data-tags="{{ img.tags }}"
     data-score="{{ img.quality_score }}"
     data-src="{{ img.local_path }}"
     data-desc="{{ img.description }}"
     onclick="openModal(this)">
  {% if img.thumbnail_path %}
  <img src="{{ img.thumbnail_path }}" alt="{{ img.description }}" loading="lazy">
  {% else %}
  <img src="{{ img.local_path }}" alt="{{ img.description }}" loading="lazy">
  {% endif %}
  <span class="score-badge">{{ "%.1f"|format(img.quality_score) }}</span>
  <div class="card-overlay">
    <div class="desc">{{ img.description }}</div>
    <div class="tags">
    {% for t in img.tag_list %}
      <span class="tag">{{ t }}</span>
    {% endfor %}
    </div>
  </div>
</div>
{% endfor %}
</div>

<div class="modal" id="modal" onclick="closeModal(event)">
  <button class="modal-close" onclick="closeModal(event)">&times;</button>
  <img id="modalImg" src="">
  <div class="modal-info">
    <div id="modalDesc"></div>
    <div class="tags" id="modalTags"></div>
  </div>
</div>

<script>
const cards = document.querySelectorAll('.card');
const tagBtns = document.querySelectorAll('.tag-btn');
const scoreRange = document.getElementById('scoreRange');
const scoreVal = document.getElementById('scoreVal');
let activeTag = null;

function filterCards() {
  const minScore = parseFloat(scoreRange.value);
  scoreVal.textContent = minScore;
  let visible = 0;
  cards.forEach(card => {
    const tags = card.dataset.tags.toLowerCase();
    const score = parseFloat(card.dataset.score);
    const tagMatch = !activeTag || tags.includes(activeTag.toLowerCase());
    const scoreMatch = score >= minScore;
    card.style.display = (tagMatch && scoreMatch) ? '' : 'none';
    if (tagMatch && scoreMatch) visible++;
  });
  const nr = document.getElementById('noResults');
  if (nr) nr.remove();
  if (visible === 0) {
    const div = document.createElement('div');
    div.id = 'noResults';
    div.className = 'no-results';
    div.textContent = 'No matching images';
    document.getElementById('gallery').appendChild(div);
  }
}

tagBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    if (activeTag === btn.dataset.tag) {
      activeTag = null;
      btn.classList.remove('active');
    } else {
      tagBtns.forEach(b => b.classList.remove('active'));
      activeTag = btn.dataset.tag;
      btn.classList.add('active');
    }
    filterCards();
  });
});

scoreRange.addEventListener('input', filterCards);

function openModal(card) {
  const modal = document.getElementById('modal');
  document.getElementById('modalImg').src = card.dataset.src;
  document.getElementById('modalDesc').textContent = card.dataset.desc;
  const tagsHtml = card.dataset.tags.split(',').filter(t=>t.trim()).map(t =>
    '<span class="tag">' + t.trim() + '</span>'
  ).join('');
  document.getElementById('modalTags').innerHTML = tagsHtml;
  modal.classList.add('active');
}

function closeModal(e) {
  if (e.target === document.getElementById('modal') || e.target.classList.contains('modal-close')) {
    document.getElementById('modal').classList.remove('active');
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.getElementById('modal').classList.remove('active');
});
</script>
</body>
</html>""")


def generate_gallery(
    images: list[dict],
    title: str,
    output_dir: str | None = None,
) -> str:
    out_dir = Path(output_dir) if output_dir else GALLERIES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    all_tags: set[str] = set()
    processed = []
    for img in images:
        tag_list = [t.strip() for t in img.get("tags", "").split(",") if t.strip()]
        all_tags.update(tag_list)
        processed.append({**img, "tag_list": tag_list})

    html = TEMPLATE.render(
        title=title,
        images=processed,
        all_tags=sorted(all_tags),
        image_count=len(processed),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )

    safe_name = title.replace(" ", "_").replace("/", "-")
    output_path = out_dir / f"{safe_name}.html"
    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
