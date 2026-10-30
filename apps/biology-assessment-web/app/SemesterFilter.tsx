import { safeSemester, type FacetResponse, type Semester } from "./lib/catalog-api";

export default function SemesterFilter({
  value,
  semesters,
  onChange,
}: {
  value: Semester | "";
  semesters: FacetResponse["semesters"];
  onChange: (value: Semester | "") => void;
}) {
  const total = semesters.reduce((sum, item) => sum + item.count, 0);
  return (
    <label>
      <span>학기</span>
      <select value={value} onChange={(event) => onChange(safeSemester(event.target.value))}>
        <option value="">전체 · {total.toLocaleString()}건</option>
        {(["1", "2"] as const).map((semester) => (
          <option key={semester} value={semester}>
            {semester}학기 · {(semesters.find((item) => item.value === semester)?.count ?? 0).toLocaleString()}건
          </option>
        ))}
      </select>
    </label>
  );
}
