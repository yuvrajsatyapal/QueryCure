"use client";

import { useSearchParams } from "next/navigation";
import { SignInView } from "./SignInView";

export function SignInFromParams() {
  const params = useSearchParams();
  return <SignInView next={params.get("next")} authError={params.get("auth_error")} />;
}
