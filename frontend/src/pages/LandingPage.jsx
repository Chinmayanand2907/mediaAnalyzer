import { useState } from 'react';
import {
  ArrowDownRight,
  ArrowRight,
  BarChart3,
  Bot,
  Check,
  ChevronRight,
  CircleDot,
  GitBranch,
  Hash,
  Layers3,
  MessageCircle,
  Network,
  Play,
  Sparkles,
  TrendingUp,
  Video,
  Zap,
} from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

const demoPerspectives = {
  momentum: {
    label: 'Momentum',
    detail: 'Reach is accelerating as conversations move from video to community.',
    metric: '84.2',
    unit: 'momentum index',
    data: [38, 42, 44, 49, 56, 61, 58, 68, 74, 81, 78, 91].map((value, i) => ({ day: i, value })),
    color: '#7565E8',
  },
  sentiment: {
    label: 'Sentiment',
    detail: 'Positive response is holding while neutral discussion becomes more specific.',
    metric: '72%',
    unit: 'positive response',
    data: [54, 57, 55, 60, 63, 67, 65, 69, 71, 74, 73, 72].map((value, i) => ({ day: i, value })),
    color: '#1C9B72',
  },
  propagation: {
    label: 'Propagation',
    detail: 'The strongest stories reach Reddit in less than a day after publishing.',
    metric: '11.4h',
    unit: 'median time to discussion',
    data: [32, 29, 34, 27, 24, 21, 25, 18, 19, 16, 14, 11].map((value, i) => ({ day: i, value })),
    color: '#D56B45',
  },
};

const sentimentData = [
  { name: 'Positive', value: 62, color: '#7565E8' },
  { name: 'Neutral', value: 24, color: '#D7D1C6' },
  { name: 'Negative', value: 14, color: '#D56B45' },
];

const connections = [
  { title: 'The quiet signal in creator tools', sub: 'r/technology', x: '13%', y: '22%', tone: 'violet' },
  { title: 'A practical take on AI workflows', sub: 'r/Entrepreneur', x: '58%', y: '13%', tone: 'lime' },
  { title: 'What the launch actually changed', sub: 'r/youtube', x: '73%', y: '63%', tone: 'orange' },
  { title: 'The community is asking better questions', sub: 'r/marketing', x: '25%', y: '70%', tone: 'violet' },
];

function navigateTo(path) {
  window.history.pushState({}, '', path);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function SectionLabel({ children, number }) {
  return <div className="editorial-label"><span>{number}</span>{children}</div>;
}

function DemoTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return <div className="editorial-tooltip"><span>Day {label}</span><strong>{payload[0].value}</strong></div>;
}

export default function LandingPage() {
  const [perspective, setPerspective] = useState('momentum');
  const active = demoPerspectives[perspective];

  return (
    <div className="editorial-page">
      <header className="editorial-nav">
        <button className="editorial-brand" onClick={() => navigateTo('/')} aria-label="EngageIQ home">
          <span className="editorial-brand-mark"><Zap size={15} /></span>
          Engage<span>IQ</span>
        </button>
        <nav className="editorial-links" aria-label="Main navigation">
          <a href="#product">Product</a>
          <a href="#capabilities">Capabilities</a>
          <a href="#how-it-works">How It Works</a>
          <a href="https://github.com/Chinmayanand2907/mediaAnalyzer" target="_blank" rel="noreferrer">GitHub <GitBranch size={13} /></a>
        </nav>
        <button className="editorial-nav-button" onClick={() => navigateTo('/dashboard')}>Open Dashboard <ArrowRight size={14} /></button>
      </header>

      <main>
        <section className="editorial-hero" id="product">
          <div className="editorial-hero-copy">
            <SectionLabel number="01">Audience intelligence / 2026</SectionLabel>
            <h1>Beyond the numbers.<br /><em>Into the conversation.</em></h1>
            <p>EngageIQ connects the reach of YouTube with the texture of Reddit, so you can understand not only what performed — but why people cared.</p>
            <div className="editorial-hero-actions">
              <button className="editorial-dark-button" onClick={() => navigateTo('/dashboard')}>Open your workspace <ArrowRight size={16} /></button>
              <a className="editorial-text-link" href="#capabilities"><Play size={13} fill="currentColor" /> See the signal</a>
            </div>
            <div className="editorial-note"><CircleDot size={13} /> Demo interface — illustrative data shown below</div>
          </div>
          <div className="editorial-hero-visual">
            <div className="editorial-hero-caption"><span>FIELD NOTE / 001</span><span>Signal, not spectacle.</span></div>
            <div className="editorial-composition">
              <div className="composition-topline"><span>ENGAGEMENT INDEX</span><span>JUN 01 — JUN 30 <ArrowDownRight size={13} /></span></div>
              <div className="composition-number">84<span>.2</span></div>
              <div className="composition-delta">+18.4% <span>vs. previous period</span></div>
              <div className="composition-graph">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={demoPerspectives.momentum.data}>
                    <defs><linearGradient id="heroFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#7565E8" stopOpacity=".34" /><stop offset="100%" stopColor="#7565E8" stopOpacity="0" /></linearGradient></defs>
                    <Area type="monotone" dataKey="value" stroke="#7565E8" strokeWidth={2} fill="url(#heroFill)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div className="composition-footer"><span>YouTube reach <b>2.48M</b></span><span>Reddit threads <b>1,284</b></span><span>Positive <b>72%</b></span></div>
            </div>
            <div className="composition-sticker">THE<br /><strong>WHY</strong><br />BEHIND<br />THE SPIKE</div>
            <div className="composition-side-note"><span>02</span><b>Conversation<br />has a shape.</b><ArrowRight size={15} /></div>
          </div>
        </section>

        <section className="editorial-ribbon" aria-label="EngageIQ capabilities">
          <span>YOUTUBE SIGNALS</span><span>REDDIT CONTEXT</span><span>SENTIMENT PATTERNS</span><span>ENGAGEMENT FORECASTS</span><span>AI INTERPRETATION</span>
        </section>

        <section className="editorial-section" id="capabilities">
          <div className="editorial-section-intro">
            <SectionLabel number="02">One view, many signals</SectionLabel>
            <h2>Analytics that reads<br /><em>between the lines.</em></h2>
            <p>Numbers tell you what happened. Conversation tells you what it meant. EngageIQ puts both on the same page.</p>
          </div>
          <div className="editorial-showcase-grid">
            <article className="showcase-panel showcase-youtube"><div className="showcase-kicker"><Video size={15} /> YouTube analytics</div><h3>Reach has a rhythm.</h3><p>Track channel momentum, video performance, and the comments that move sentiment.</p><div className="mini-line-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={demoPerspectives.momentum.data}><Line type="monotone" dataKey="value" stroke="#7565E8" strokeWidth={2.5} dot={false} /><XAxis dataKey="day" hide /><YAxis hide /></LineChart></ResponsiveContainer></div><div className="showcase-stat"><strong>2.48M</strong><span>total views<br />across 12 videos</span></div></article>
            <article className="showcase-panel showcase-reddit"><div className="showcase-kicker"><MessageCircle size={15} /> Reddit analytics</div><h3>Context lives here.</h3><p>Find the themes, reactions, and emerging questions behind community activity.</p><div className="keyword-cloud"><span>workflow</span><span>creator tools</span><span className="keyword-large">AI</span><span>strategy</span><span>launch</span></div><div className="showcase-stat"><strong>1,284</strong><span>active discussions<br />across 18 communities</span></div></article>
            <article className="showcase-panel showcase-cross"><div className="showcase-kicker"><Network size={15} /> Cross-platform discovery</div><h3>Follow the story.</h3><p>See how content travels, where it lands, and how reception changes along the way.</p><div className="cross-flow"><span className="flow-node flow-video"><Video size={15} /></span><i /><span className="flow-node flow-reddit"><MessageCircle size={15} /></span><i /><span className="flow-node flow-community"><UsersIcon /></span></div><div className="showcase-stat"><strong>11.4h</strong><span>median propagation<br />from video to discussion</span></div></article>
          </div>
        </section>

        <section className="editorial-lab" id="lab">
          <div className="lab-header"><div><SectionLabel number="03">The analytics laboratory</SectionLabel><h2>Choose your<br /><em>point of view.</em></h2></div><p>Switch perspectives to see how the same body of audience data tells a different story. <span>Demo data.</span></p></div>
          <div className="lab-shell">
            <div className="lab-tabs">{Object.entries(demoPerspectives).map(([key, item]) => <button key={key} className={perspective === key ? 'active' : ''} onClick={() => setPerspective(key)}>{item.label}<ChevronRight size={14} /></button>)}</div>
            <div className="lab-main">
              <div className="lab-copy"><span className="lab-overline">CURRENT LENS / {active.label.toUpperCase()}</span><strong>{active.metric}</strong><small>{active.unit}</small><p>{active.detail}</p><a href="/dashboard" onClick={(event) => { event.preventDefault(); navigateTo('/dashboard'); }}>Explore live data <ArrowRight size={14} /></a></div>
              <div className="lab-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={active.data}><CartesianGrid stroke="#e4e0d8" vertical={false} /><XAxis dataKey="day" tick={{ fill: '#8c8981', fontSize: 10 }} tickLine={false} axisLine={false} /><YAxis hide /><Tooltip content={<DemoTooltip />} /><Area type="monotone" dataKey="value" stroke={active.color} fill={active.color} fillOpacity=".1" strokeWidth={3} /></AreaChart></ResponsiveContainer></div>
            </div>
          </div>
        </section>

        <section className="editorial-section connection-section">
          <div className="connection-copy"><SectionLabel number="04">Cross-platform discovery</SectionLabel><h2>Every video leaves<br /><em>a trace.</em></h2><p>Map the journey from a YouTube upload to the Reddit threads, communities, and questions it creates.</p><div className="connection-legend"><span><i className="legend-video" /> YouTube video</span><span><i className="legend-reddit" /> Reddit discussion</span></div></div>
          <div className="connection-map"><div className="map-grid" /><div className="map-center"><Video size={20} /><span>THE SIGNAL</span></div>{connections.map((connection) => <div className={`connection-node ${connection.tone}`} style={{ left: connection.x, top: connection.y }} key={connection.title}><span className="node-icon"><MessageCircle size={14} /></span><div><b>{connection.title}</b><small>{connection.sub}</small></div></div>)}<svg className="connection-lines" viewBox="0 0 600 400" preserveAspectRatio="none"><path d="M300 190 C230 140 150 100 90 90 M300 190 C360 120 440 90 520 80 M300 205 C420 260 460 290 500 315 M290 210 C220 260 150 300 105 330" /></svg></div>
        </section>

        <section className="editorial-section split-section">
          <div className="split-demo sentiment-demo"><SectionLabel number="05">Sentiment, with nuance</SectionLabel><h2>Measure the<br /><em>temperature.</em></h2><p>Go beyond a single score. Compare how audiences feel, platform by platform.</p><div className="sentiment-chart"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={sentimentData} dataKey="value" innerRadius={66} outerRadius={94} paddingAngle={3}>{sentimentData.map((item) => <Cell key={item.name} fill={item.color} />)}</Pie></PieChart></ResponsiveContainer><div className="sentiment-center"><strong>72%</strong><span>positive</span></div></div><div className="sentiment-legend">{sentimentData.map((item) => <span key={item.name}><i style={{ background: item.color }} />{item.name}<b>{item.value}%</b></span>)}</div></div>
          <div className="split-demo forecast-demo"><SectionLabel number="06">Engagement forecasting</SectionLabel><h2>Know what<br /><em>comes next.</em></h2><p>Use historical signals to model the next chapter — before it arrives.</p><div className="forecast-chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={[{ n: 'W1', actual: 42, forecast: 42 }, { n: 'W2', actual: 58, forecast: 58 }, { n: 'W3', actual: 65, forecast: 65 }, { n: 'W4', actual: 72, forecast: 72 }, { n: 'W5', actual: null, forecast: 81 }, { n: 'W6', actual: null, forecast: 94 }]}><CartesianGrid stroke="#e4e0d8" vertical={false} /><XAxis dataKey="n" tick={{ fill: '#8c8981', fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis hide /><Bar dataKey="actual" fill="#171923" radius={[3, 3, 0, 0]} /><Bar dataKey="forecast" fill="#D5F36A" radius={[3, 3, 0, 0]} /></BarChart></ResponsiveContainer></div><div className="forecast-key"><span><i className="actual-key" /> Observed</span><span><i className="forecast-key-mark" /> Forecast</span><strong>+31% expected lift</strong></div></div>
        </section>

        <section className="editorial-analyst" id="analyst"><div className="analyst-quote"><span className="quote-mark">“</span><p>The latest video is outperforming its channel average because the Reddit conversation is moving from reaction to recommendation.</p><span className="quote-source"><Bot size={14} /> EngageIQ analyst / grounded in your data</span></div><div className="analyst-side"><SectionLabel number="07">The AI analyst</SectionLabel><h2>Ask the data<br /><em>better questions.</em></h2><p>Not a generic chatbot. A context-aware analyst that knows the platform, the content, and the signal in front of you.</p><button className="editorial-dark-button" onClick={() => navigateTo('/dashboard')}>Try the analyst <ArrowRight size={15} /></button></div></section>

        <section className="editorial-section how-section" id="how-it-works"><SectionLabel number="08">How it works</SectionLabel><div className="how-grid"><div><span>01</span><h3>Connect the sources</h3><p>Ingest YouTube channels and Reddit communities through their official APIs.</p></div><div><span>02</span><h3>Read the signals</h3><p>Sentiment, topics, engagement, and propagation are analyzed in one pipeline.</p></div><div><span>03</span><h3>Make the move</h3><p>Turn a clearer understanding of your audience into your next decision.</p></div></div><div className="tech-strip"><span>POWERED BY</span><b>React 19</b><b>FastAPI</b><b>PostgreSQL</b><b>MongoDB</b><b>RoBERTa</b><b>XGBoost</b><b>Gemini</b></div></section>

        <section className="editorial-cta"><div className="cta-rule" /><SectionLabel number="09">Your next signal is already there</SectionLabel><h2>Stop reporting<br /><em>the past.</em></h2><p>Start understanding what your audience is saying now.</p><button className="editorial-lime-button" onClick={() => navigateTo('/dashboard')}>Open EngageIQ <ArrowRight size={16} /></button></section>
      </main>
      <footer className="editorial-footer"><button className="editorial-brand" onClick={() => navigateTo('/')}><span className="editorial-brand-mark"><Zap size={13} /></span> Engage<span>IQ</span></button><span>Social intelligence for the curious.</span><span>© {new Date().getFullYear()} EngageIQ</span></footer>
    </div>
  );
}

function UsersIcon() {
  return <Layers3 size={15} />;
}
