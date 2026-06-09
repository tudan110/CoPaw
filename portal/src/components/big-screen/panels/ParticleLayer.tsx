const PARTICLES = [
  { left: "22%", top: "30%", delay: "0s" },
  { left: "62%", top: "22%", delay: "0.6s" },
  { left: "78%", top: "62%", delay: "1.1s" },
  { left: "34%", top: "72%", delay: "0.3s" },
  { left: "88%", top: "40%", delay: "1.6s" },
  { left: "14%", top: "54%", delay: "2s" },
  { left: "50%", top: "84%", delay: "0.9s" },
  { left: "42%", top: "18%", delay: "1.4s" },
  { left: "70%", top: "50%", delay: "0.7s" },
];

export function ParticleLayer() {
  return (
    <div className="bs-particle-layer" aria-hidden="true">
      {PARTICLES.map((p, i) => (
        <div
          key={i}
          className="bs-particle"
          style={{
            left: p.left,
            top: p.top,
            animationDelay: p.delay,
          }}
        />
      ))}
    </div>
  );
}
