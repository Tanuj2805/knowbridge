// The Project Nimbus cast. Only used when DEMO_MODE=true.
export type Persona = {
  id: string;
  name: string;
  email: string;
  role: string;
  blurb: string;
};

export const PERSONAS: Persona[] = [
  {
    id: "aarav",
    name: "Aarav Mehta",
    email: "aarav@nimbus.demo",
    role: "Leaving",
    blurb: "Final-year tech lead of the fest app. Graduates in three weeks.",
  },
  {
    id: "meera",
    name: "Meera Iyer",
    email: "meera@nimbus.demo",
    role: "Taking over",
    blurb: "Second-year student picking up the backend.",
  },
  {
    id: "priya",
    name: "Priya Nair",
    email: "priya@nimbus.demo",
    role: "Approver",
    blurb: "Club president. Signs off before anything is shared.",
  },
  {
    id: "kabir",
    name: "Kabir Singh",
    email: "kabir@nimbus.demo",
    role: "Admin",
    blurb: "Club tech admin. Connects sources and sets who sees what.",
  },
];

export function personaById(id: string): Persona | undefined {
  return PERSONAS.find((p) => p.id === id);
}
