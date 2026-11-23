export async function cancelOrder(orderId: string): Promise<void> {
  await fetch(`/orders/${orderId}/cancel`, { method: "POST" });
}
