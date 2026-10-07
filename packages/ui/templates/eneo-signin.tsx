import { SignInScreen } from "@eneo-ai/module-kit/session";

export default function EneoSignin({ productName = "Eneo-modul", unreachable = false }: {
  productName?: string;
  unreachable?: boolean;
}) {
  return <SignInScreen productName={productName} title="Logga in" next="/flows" unreachable={unreachable} />;
}
