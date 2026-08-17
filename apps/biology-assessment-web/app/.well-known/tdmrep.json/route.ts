const TDM_RESERVATION = {
  version: "1.0",
  policy: "reserved",
  owner: "N의 생명과학",
  contact: "https://www.instagram.com/n_life_science",
  scope: [
    "service code and design",
    "assessment selection and classification",
    "safe source transformations",
    "teacher-facing analysis and writing",
  ],
  note: "Text and data mining, model training, fine-tuning, and dataset construction are reserved. Public-source documents remain subject to their original publisher terms.",
};

export function GET() {
  return Response.json(TDM_RESERVATION, {
    headers: { "X-Robots-Tag": "noindex, nofollow, noarchive" },
  });
}
