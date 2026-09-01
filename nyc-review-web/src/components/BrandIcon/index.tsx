interface BrandIconProps {
  size?: number;
}

export default function BrandIcon({ size = 48 }: BrandIconProps) {
  return (
    <img
      src="/brand/nyc-review-icon.png"
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable="false"
      style={{ display: 'block' }}
    />
  );
}
