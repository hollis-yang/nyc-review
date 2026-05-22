import { Swiper, SwiperSlide } from 'swiper/react';
import { Pagination } from 'swiper/modules';
import 'swiper/css';
import 'swiper/css/pagination';
import styles from './ImageSwiper.module.css';

interface ImageSwiperProps {
  images: string[];
}

export default function ImageSwiper({ images }: ImageSwiperProps) {
  if (!images || images.length === 0) return null;

  return (
    <div className={styles.container}>
      <Swiper
        modules={[Pagination]}
        pagination={{ clickable: true }}
        className={styles.swiper}
      >
        {images.map((src, i) => (
          <SwiperSlide key={i}>
            <div className={styles.slide}>
              <img src={src} alt="" />
            </div>
          </SwiperSlide>
        ))}
      </Swiper>
    </div>
  );
}
