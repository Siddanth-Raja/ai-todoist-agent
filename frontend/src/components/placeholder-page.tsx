type PlaceholderPageProps = {
  title: string;
  description: string;
  accent: "moss" | "coral" | "gold";
};

const accentClasses = {
  moss: "border-moss/30 bg-moss/10 text-moss",
  coral: "border-coral/30 bg-coral/10 text-coral",
  gold: "border-gold/30 bg-gold/10 text-gold",
};

export function PlaceholderPage({ title, description, accent }: PlaceholderPageProps) {
  return (
    <section className="mx-auto max-w-4xl">
      <div className="relative overflow-hidden rounded-[2.25rem] border border-white/10 bg-white/[0.055] p-6 shadow-soft backdrop-blur-2xl md:p-10">
        <div className="absolute right-[-7rem] top-[-7rem] h-72 w-72 rounded-full bg-white/10 blur-3xl" />
        <div className={`relative mb-8 inline-flex min-h-10 items-center rounded-full border px-4 text-xs ${accentClasses[accent]}`}>
          Planned
        </div>
        <h3 className="relative max-w-2xl text-3xl font-semibold tracking-normal text-pearl md:text-5xl">{title}</h3>
        <p className="relative mt-5 max-w-xl text-base leading-7 text-stone-400">{description}</p>
      </div>
    </section>
  );
}
