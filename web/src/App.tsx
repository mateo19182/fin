import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Overview } from "./pages/Overview";
import { Review } from "./pages/Review";
import { Transactions } from "./pages/Transactions";
import { Spending } from "./pages/Spending";
import { Portfolio } from "./pages/Portfolio";
import { Sources } from "./pages/Sources";
import { Close } from "./pages/Close";
import { Guide } from "./pages/Guide";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="review" element={<Review />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="spending" element={<Spending />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="sources" element={<Sources />} />
        <Route path="close" element={<Close />} />
        <Route path="guide" element={<Guide />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
