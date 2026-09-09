import { Loader } from "@/components/ui/Loader";

type LoadingStateProps = {
  label?: string;
};

export function LoadingState({ label = "Loading" }: LoadingStateProps) {
  return (
    <div className="kern-state">
      <Loader label={label} size="lg" />
    </div>
  );
}
