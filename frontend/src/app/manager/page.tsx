import { redirect } from "next/navigation";

export default function ManagerIndexPage() {
  redirect("/manager/applicants");
}
