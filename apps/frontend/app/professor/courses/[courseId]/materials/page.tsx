import { ProfessorMaterialsClient } from "../../../materials/professor-materials-client";

export default async function ProfessorCourseMaterialsPage({
  params
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  return <ProfessorMaterialsClient courseId={courseId} />;
}
