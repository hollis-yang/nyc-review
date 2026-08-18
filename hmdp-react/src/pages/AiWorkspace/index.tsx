import { useMemo, useState } from 'react';
import { Toast } from 'antd-mobile';
import { LeftOutline } from 'antd-mobile-icons';
import { useNavigate } from 'react-router-dom';
import { runMultiAgent, type AgentRunResponse } from '../../api/agent';
import styles from './AiWorkspace.module.css';

const CATEGORIES = [
  'Food & Dining',
  'Cafes & Desserts',
  'Bars & Nightlife',
  'Entertainment & Attractions',
  'Fitness & Wellness',
  'Beauty & Personal Care',
];

const TAGS = ['quiet', 'vegan_options', 'wheelchair_accessible', 'good_for_groups', 'late_night'];

export default function AiWorkspace() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('Quiet dinner near MoMA with vegan options');
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [neighborhood, setNeighborhood] = useState('Midtown');
  const [partySize, setPartySize] = useState(2);
  const [budget, setBudget] = useState(120);
  const [tags, setTags] = useState<string[]>(['quiet', 'vegan_options']);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AgentRunResponse | null>(null);

  const evidenceByShop = useMemo(
    () => new Map(result?.evidence.evidence.map((item) => [item.shop_id, item]) || []),
    [result],
  );

  const toggleTag = (tag: string) => {
    setTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  };

  const submit = async () => {
    if (!query.trim()) {
      Toast.show({ icon: 'fail', content: 'Please describe what you need.' });
      return;
    }
    setLoading(true);
    try {
      const response = await runMultiAgent({
        mode: 'multi',
        constraints: {
          query: query.trim(),
          latitude: 40.7614,
          longitude: -73.9776,
          neighborhood: neighborhood.trim() || undefined,
          category,
          party_size: partySize,
          budget_cents: Math.round(budget * 100),
          desired_tags: tags,
        },
      });
      setResult(response);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Agent service is unavailable.';
      Toast.show({ icon: 'fail', content: message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <button className={styles.back} onClick={() => navigate(-1)} aria-label="Back">
          <LeftOutline />
        </button>
        <div>
          <div className={styles.eyebrow}>NYC LOCAL INTELLIGENCE</div>
          <h1>AI Planner</h1>
        </div>
        <span className={styles.mode}>MULTI</span>
      </header>

      <main className={styles.content}>
        <section className={styles.composer}>
          <label>
            What should the agents plan?
            <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={3} />
          </label>
          <div className={styles.grid}>
            <label>
              Category
              <select value={category} onChange={(event) => setCategory(event.target.value)}>
                {CATEGORIES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>
              Neighborhood
              <input value={neighborhood} onChange={(event) => setNeighborhood(event.target.value)} />
            </label>
            <label>
              Party size
              <input
                type="number"
                min={1}
                max={50}
                value={partySize}
                onChange={(event) => setPartySize(Number(event.target.value))}
              />
            </label>
            <label>
              Total budget (USD)
              <input
                type="number"
                min={0}
                value={budget}
                onChange={(event) => setBudget(Number(event.target.value))}
              />
            </label>
          </div>
          <div className={styles.tags}>
            {TAGS.map((tag) => (
              <button
                key={tag}
                className={tags.includes(tag) ? styles.tagActive : styles.tag}
                onClick={() => toggleTag(tag)}
              >
                {tag.replaceAll('_', ' ')}
              </button>
            ))}
          </div>
          <button className={styles.run} disabled={loading} onClick={submit}>
            {loading ? 'Agents are working…' : 'Run verified plan'}
          </button>
          <p className={styles.safety}>
            AI can research and plan. Flash-sale checkout remains a manual action on the shop page.
          </p>
        </section>

        {result && (
          <section className={styles.results}>
            <div className={styles.statusRow}>
              <span className={result.verification.valid ? styles.verified : styles.invalid}>
                {result.verification.valid ? 'Verified' : 'Needs review'}
              </span>
              <span>{result.metadata.rag?.toUpperCase()} RAG · {result.metadata.adapter} tools</span>
            </div>
            <h2>{result.summary}</h2>

            <div className={styles.timeline}>
              {(result.metadata.events || []).map((event) => (
                <span key={event}>{event.replace(':', ' → ').replaceAll('_', ' ')}</span>
              ))}
            </div>

            {result.candidates.candidates.map((shop) => {
              const evidence = evidenceByShop.get(shop.shop_id);
              return (
                <article className={styles.card} key={shop.shop_id}>
                  <div className={styles.cardHeading}>
                    <div>
                      <h3>{shop.name}</h3>
                      <p>{shop.neighborhood} · {shop.category}</p>
                    </div>
                    <strong>${(shop.avg_price_cents / 100).toFixed(0)}</strong>
                  </div>
                  <div className={styles.score}>★ {shop.score.toFixed(1)} · {shop.tags.join(' · ')}</div>
                  {evidence?.citations.map((citation) => (
                    <blockquote key={citation.citation_id}>
                      “{citation.excerpt}”
                      <cite>{citation.content_type} · {citation.source_id}</cite>
                    </blockquote>
                  ))}
                  <button className={styles.openShop} onClick={() => navigate(`/shop-detail/${shop.shop_id}`)}>
                    Open shop page
                  </button>
                </article>
              );
            })}

            {!result.verification.valid && result.verification.issues.map((issue) => (
              <div className={styles.issue} key={`${issue.code}-${issue.shop_id || 0}`}>
                {issue.code}: {issue.message}
              </div>
            ))}
          </section>
        )}
      </main>
    </div>
  );
}
