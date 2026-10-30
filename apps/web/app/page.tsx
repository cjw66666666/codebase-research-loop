/**
 * 站点首页只负责跳转到项目工作台。
 */
import { redirect } from "next/navigation";

export default function HomePage() {
  redirect("/projects");
}
