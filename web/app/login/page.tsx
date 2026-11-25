import { Suspense } from "react";
import { LoginForm } from "@/components/auth/LoginForm";
import { LoadingState } from "@/components/states/LoadingState";

export default function LoginPage() {
  return (
    <div className="kern-page kern-login-page">
      <Suspense
        fallback={
          <div className="kern-content-state" aria-busy="true">
            <LoadingState label="Loading sign in" />
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
