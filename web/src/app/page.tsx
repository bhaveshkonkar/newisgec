import { redirect } from "next/navigation";

export default function RootPage() {
  // The only entry point is the project list -- there is no dashboard.
  redirect("/projects");
}