import { useEffect, useState } from "react";

import { formatTime, HOME_TZ, HOME_TZ_LABEL } from "./time";

export function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="nx-clock" aria-label="Clock">
      <span>
        <b data-testid="clock-home">{formatTime(now, HOME_TZ)}</b> {HOME_TZ_LABEL}
      </span>
      <span>
        <span data-testid="clock-utc">{formatTime(now, "UTC")}</span> UTC
      </span>
    </div>
  );
}
